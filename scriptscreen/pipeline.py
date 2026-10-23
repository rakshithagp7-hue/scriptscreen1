"""Orchestrator. Order matters: audio FIRST, then timings derive from audio (no drift).

Speed: the per-scene work (voice + image + optional AI clip) is independent between scenes,
so it runs 3 scenes at a time instead of one after another.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import adapt, assemble, config, llm, metrics, motion, visuals, voice
from .util import Trace, key_of

MAX_PARALLEL_SCENES = 3  # keep small: free image/TTS services rate-limit


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:30] or "audience"


def run(topic, script, audience, language="en", fmt="horizontal", target_seconds=config.TARGET_SECONDS,
        out_dir=None, captions=True):
    label = slug(audience)
    out = Path(out_dir or config.OUT_DIR / label)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    trace = Trace(label)
    warnings = []
    size = config.FORMATS[fmt]
    trace.log("setup", f"audience='{audience}' lang={language} format={fmt}{size} "
                       f"llm={'on' if llm.available() else 'OFF (heuristic)'} offline={config.OFFLINE} "
                       f"ai_clips_max={config.AI_CLIPS_MAX if motion.available() else 0}")

    # Step 1+4: analyse + adapt (critic loop inside)
    data, verdict = adapt.adapt(topic, script, audience, language, target_seconds, trace)
    profile, scenes = data["profile"], data["scenes"]
    trace.log("adapt", f"{len(scenes)} scenes, pace={profile['pace_wpm']}wpm, style='{profile['visual_style'][:50]}'")

    # The offline adapter only writes English. Never read English text with a Hindi/Kannada voice:
    # switch this video to English (voice + captions) and say so.
    if language != "en" and not verdict.get("translated"):
        msg = (f"Translation unavailable (LLM busy), so this video was made in English instead of "
               f"{adapt.LANG_NAMES.get(language, language)}. Click Generate again in a minute.")
        warnings.append(msg)
        trace.log("check", msg)
        language = "en"

    # Step 3 then 2: voice first (real durations), visuals share one style + one seed.
    # The first AI_CLIPS_MAX scenes also get a real AI-generated video clip (Magic Hour).
    seed = int(key_of(topic, audience), 16) % 100000
    minor = adapt.is_minor_audience(audience)

    def scene_assets(args):
        i, sc = args
        wav = out / "frames" / f"scene{i}.wav"
        v = voice.synth_scene(sc["narration"], wav, profile, language, trace)
        img, src = visuals.get_image(sc, profile, size, seed, i, trace, minor)
        clip = None
        if i < config.AI_CLIPS_MAX and motion.available():
            prompt = visuals.build_prompt(sc["image_prompt"], profile, minor) + " " + motion.MOTION_HINT
            clip = motion.make_clip(prompt, fmt, trace)
        return {"narration": sc["narration"], "image": img, "clip": clip, "wav": wav, **v}, src

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SCENES) as ex:
        results = list(ex.map(scene_assets, enumerate(scenes)))  # keeps scene order

    infos = []
    for i, (info, src) in enumerate(results):
        trace.log("scene", f"{i + 1}/{len(scenes)} audio={info['duration']:.1f}s ({info['engine']}) image={src} "
                           f"motion={'AI-clip' if info['clip'] else 'ken-burns'}")
        infos.append(info)

    total = sum(i["duration"] for i in infos)
    if not config.MIN_SECONDS <= total <= config.MAX_SECONDS:
        warnings.append(f"video is {total:.0f}s, outside the {config.MIN_SECONDS}-{config.MAX_SECONDS}s target")
        trace.log("check", warnings[-1])

    # Step 5: assemble (falls back to asset package if encoding fails)
    timeline, video = assemble.build_video(infos, out, captions=captions and language == "en")
    if video is None:
        warnings.append("video encode failed; asset package saved instead")
    trace.log("assemble", f"video={'ok' if video else 'FAILED'} total={total:.1f}s")

    # Step 6: export
    card = metrics.scorecard(profile, scenes, infos, verdict, language, fmt)
    card["ai_video_clips"] = sum(1 for i in infos if i.get("clip"))
    (out / "adapted.json").write_text(json.dumps({"profile": profile, "scenes": scenes, "timeline": timeline},
                                                 indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "scorecard.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    trace.save(out / "trace.json")
    return {"audience": audience, "dir": out, "video": video, "scorecard": card, "profile": profile,
            "scenes": scenes, "trace": trace.events, "warnings": warnings}


def compare(topic, script, audiences, out_root=None, **kw):
    """The 'Audience Diff': same script, several audiences, one comparison table."""
    root = Path(out_root or config.OUT_DIR)
    results = {a: run(topic, script, a, out_dir=root / slug(a), **kw) for a in audiences}
    cards = {a: r["scorecard"] for a, r in results.items()}
    md = [f"# Audience Diff: {topic}\n", metrics.compare_markdown(cards), "\n## Adapted narration\n"]
    for a, r in results.items():
        md.append(f"### {a}\n" + "\n".join(f"{i + 1}. {s['narration']}" for i, s in enumerate(r["scenes"])) + "\n")
    root.mkdir(parents=True, exist_ok=True)
    (root / "compare.md").write_text("\n".join(md), encoding="utf-8")
    return results