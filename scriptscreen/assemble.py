"""Step 5: assembly. Timings come from real audio, captions are burned in and synced per chunk.

Renderers:
  - build_video()         animated: AI clip (if the scene has one) or Ken Burns motion on the image,
                          + xfade transitions + timed captions
  - build_video_static()  plain slideshow, used automatically if the animated render fails
"""
import wave
from pathlib import Path

from PIL import Image, ImageDraw

from .util import run_ffmpeg
from .visuals import get_font
from .voice import PAD


# ------------------------------------------------------------------ shared helpers
def _chunks(text, max_words=7):
    out, cur = [], []
    for w in text.split():
        cur.append(w)
        if len(cur) >= max_words or (len(cur) >= 3 and w[-1] in ",.;!?"):
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    lines.append(cur)
    return lines


def _caption_frame(base_path, text, out_path):
    img = Image.open(base_path).convert("RGBA")
    w, h = img.size
    font = get_font(max(22, min(w, h) // 17))
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    lines = _wrap(d, text, font, w * 0.84)
    lh = int(font.size * 1.3)
    box_h, pad = len(lines) * lh, int(font.size * 0.5)
    y1 = h - int(h * 0.06)
    y0 = y1 - box_h - 2 * pad
    widest = max(d.textlength(ln, font=font) for ln in lines)
    d.rounded_rectangle([(w - widest) / 2 - pad, y0, (w + widest) / 2 + pad, y1], radius=16, fill=(0, 0, 0, 160))
    y = y0 + pad
    for ln in lines:
        d.text(((w - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill="white")
        y += lh
    Image.alpha_composite(img, over).convert("RGB").save(out_path)


def _srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _concat_wavs(paths, out):
    with wave.open(str(paths[0]), "rb") as w0:
        params = w0.getparams()
    with wave.open(str(out), "wb") as wo:
        wo.setparams(params)
        for p in paths:
            with wave.open(str(p), "rb") as wi:
                wo.writeframes(wi.readframes(wi.getnframes()))


# ------------------------------------------------------------------ static version (fallback)
def build_video_static(infos, out_dir, captions=True):
    """infos: [{narration, image, wav, duration}]. Returns (timeline, video_path_or_None)."""
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frames, timeline, srt, t, n = [], [], [], 0.0, 1
    for i, info in enumerate(infos):
        dur = info["duration"]
        timeline.append({"scene": i + 1, "start": round(t, 2), "end": round(t + dur, 2),
                         "narration": info["narration"], "image": str(info["image"]), "audio": str(info["wav"])})
        if captions:
            chunks = _chunks(info["narration"])
            weights = [len(c) for c in chunks]
            spoken = max(0.1, dur - PAD)
            ct = t
            for j, (c, wgt) in enumerate(zip(chunks, weights)):
                cd = spoken * wgt / sum(weights) + (PAD if j == len(chunks) - 1 else 0)
                fp = frames_dir / f"s{i}_c{j}.png"
                _caption_frame(info["image"], c, fp)
                frames.append((fp, cd))
                srt.append(f"{n}\n{_srt_time(ct)} --> {_srt_time(ct + cd)}\n{c}\n")
                ct += cd
                n += 1
        else:
            frames.append((Path(info["image"]), dur))
        t += dur

    if captions:
        (out_dir / "captions.srt").write_text("\n".join(srt), encoding="utf-8")

    video = out_dir / "video.mp4"
    try:
        audio = out_dir / "voiceover.wav"
        _concat_wavs([i["wav"] for i in infos], audio)
        lst = out_dir / "frames.txt"
        q = lambda p: str(Path(p).resolve().as_posix()).replace("'", "'\\''")  # noqa: E731
        lines = []
        for fp, d in frames:
            lines += [f"file '{q(fp)}'", f"duration {d:.3f}"]
        lines.append(f"file '{q(frames[-1][0])}'")
        lst.write_text("\n".join(lines), encoding="utf-8")
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-i", audio,
                    "-vf", "fps=24,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                    "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", video])
        return timeline, video
    except Exception as e:  # noqa: BLE001
        print(f"  [assemble] video encode failed: {e}. Asset package (images + audio + timeline) is still saved.")
        return timeline, None


# ------------------------------------------------------------------ animated version
FPS = 24
CLIP_SECONDS = 5.0  # length of one AI clip (see motion.py)
MOTIONS = [  # (zoom expr, x expr, y expr); {N} = frames in the clip
    ("1+0.18*on/{N}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),          # slow zoom in
    ("1.15", "(iw-iw/zoom)*on/{N}", "(ih-ih/zoom)/2"),              # pan right
    ("1.18-0.18*on/{N}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),       # zoom out
    ("1.15", "(iw-iw/zoom)*(1-on/{N})", "(ih-ih/zoom)/2"),          # pan left
]
TRANSITIONS = ["fade", "slideleft", "circleopen", "wipeleft", "smoothleft"]


def _caption_overlay(size, text, out_path):
    """Transparent PNG containing only the caption box."""
    w, h = size
    over = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    font = get_font(max(22, min(w, h) // 17))
    lines = _wrap(d, text, font, w * 0.84)
    lh = int(font.size * 1.3)
    pad = int(font.size * 0.5)
    y1 = h - int(h * 0.06)
    y0 = y1 - len(lines) * lh - 2 * pad
    widest = max(d.textlength(ln, font=font) for ln in lines)
    d.rounded_rectangle([(w - widest) / 2 - pad, y0, (w + widest) / 2 + pad, y1], radius=16, fill=(0, 0, 0, 160))
    y = y0 + pad
    for ln in lines:
        d.text(((w - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill="white")
        y += lh
    over.save(out_path)


def _ai_base_filter(length, size):
    """Fit a ~5 s AI clip to the scene length: slow it down (max 1.6x), then play it forward and
    backward ('boomerang') so water-like motion keeps going, then trim to the exact length."""
    W, H = size
    f = min(1.6, max(1.0, length / CLIP_SECONDS))
    return (f"[0:v]setpts={f:.3f}*PTS,fps={FPS},split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0,"
            f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
            f"tpad=stop_mode=clone:stop_duration=4,trim=duration={length:.3f},setpts=PTS-STARTPTS[b0]")


def _scene_clip(info, length, idx, size, caps, out):
    """One scene: AI clip (if present) or Ken Burns motion on the image, plus timed caption overlays."""
    W, H = size
    N = int(length * FPS) + 1
    if info.get("clip"):
        args = ["-i", info["clip"]]
        fc = [_ai_base_filter(length, size)]
    else:
        z, x, y = (e.format(N=N) for e in MOTIONS[idx % len(MOTIONS)])
        args = ["-i", info["image"]]
        fc = [f"[0:v]scale={W * 2}:{H * 2},zoompan=z='{z}':x='{x}':y='{y}':d={N}:s={W}x{H}:fps={FPS}[b0]"]
    for png, _, _ in caps:
        args += ["-loop", "1", "-t", f"{length:.3f}", "-i", png]
    for k, (_, a, b) in enumerate(caps, start=1):
        fc.append(f"[b{k - 1}][{k}:v]overlay=enable='between(t,{a:.3f},{b:.3f})'[b{k}]")
    fc.append(f"[b{len(caps)}]format=yuv420p[v]")
    run_ffmpeg([*args, "-filter_complex", ";".join(fc), "-map", "[v]", "-r", FPS, "-t", f"{length:.3f}",
                "-c:v", "libx264", "-preset", "veryfast", "-an", out])


def build_video(infos, out_dir, captions=True):
    """Animated video. Falls back to the static slideshow if anything fails."""
    try:
        return _build_animated(infos, out_dir, captions)
    except Exception as e:  # noqa: BLE001
        print(f"  [assemble] animation failed ({str(e)[:200]}). Falling back to static video.")
        return build_video_static(infos, out_dir, captions)


def _build_animated(infos, out_dir, captions):
    out_dir = Path(out_dir)
    work = out_dir / "frames"
    work.mkdir(parents=True, exist_ok=True)
    size = Image.open(infos[0]["image"]).size
    durs = [i["duration"] for i in infos]
    T = round(min(0.4, min(durs) / 3), 2)  # transition length

    timeline, srt, clips, t, n = [], [], [], 0.0, 1
    for i, info in enumerate(infos):
        dur = info["duration"]
        length = dur + (T if i < len(infos) - 1 else 0)  # overlap region for the transition
        timeline.append({"scene": i + 1, "start": round(t, 2), "end": round(t + dur, 2),
                         "narration": info["narration"], "image": str(info["image"]), "audio": str(info["wav"]),
                         "motion": "ai-clip" if info.get("clip") else "ken-burns"})
        caps = []
        if captions:
            chunks = _chunks(info["narration"])
            weights = [len(c) for c in chunks]
            spoken = max(0.1, dur - PAD)
            ct = 0.0
            for j, (c, wgt) in enumerate(zip(chunks, weights)):
                cd = spoken * wgt / sum(weights) + (PAD if j == len(chunks) - 1 else 0)
                png = work / f"cap_s{i}_c{j}.png"
                _caption_overlay(size, c, png)
                end = length if j == len(chunks) - 1 else ct + cd
                caps.append((png, ct, end))
                srt.append(f"{n}\n{_srt_time(t + ct)} --> {_srt_time(t + ct + cd)}\n{c}\n")
                ct += cd
                n += 1
        scene_path = work / f"clip{i}.mp4"
        try:
            _scene_clip(info, length, i, size, caps, scene_path)
        except Exception as e:  # noqa: BLE001
            if not info.get("clip"):
                raise
            print(f"  [assemble] scene {i + 1}: AI clip failed to render ({str(e)[:120]}); using Ken Burns for it.")
            info = {**info, "clip": None}
            _scene_clip(info, length, i, size, caps, scene_path)
        clips.append(scene_path)
        t += dur

    if captions:
        (out_dir / "captions.srt").write_text("\n".join(srt), encoding="utf-8")

    audio = out_dir / "voiceover.wav"
    _concat_wavs([i["wav"] for i in infos], audio)

    args = []
    for c in clips:
        args += ["-i", c]
    args += ["-i", audio]
    if len(clips) == 1:
        fc, last = "[0:v]null[vout]", "[vout]"
    else:
        parts, offset, prev = [], 0.0, "[0:v]"
        for k in range(1, len(clips)):
            offset += durs[k - 1]
            tr = TRANSITIONS[(k - 1) % len(TRANSITIONS)]
            nxt = f"[x{k}]"
            parts.append(f"{prev}[{k}:v]xfade=transition={tr}:duration={T}:offset={offset:.3f}{nxt}")
            prev = nxt
        fc, last = ";".join(parts), prev
    video = out_dir / "video.mp4"
    run_ffmpeg([*args, "-filter_complex", fc, "-map", last, "-map", f"{len(clips)}:a",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", video])
    return timeline, video
