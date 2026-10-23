"""Step 2: one image per scene, all sharing ONE style bible + seed for visual consistency."""
import io
import random
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import config
from .util import cache_file, key_of, retry

UNSAFE = ("gore", "blood", "weapon", "gun", "nude", "violent", "corpse")


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def get_font(size):
    for p in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "arialbd.ttf", "Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def build_prompt(scene_prompt, profile, minor):
    subject = scene_prompt
    for w in UNSAFE:
        subject = subject.replace(w, "")
    safe = "child-friendly, safe for all ages, " if minor else ""
    pal = ", ".join(profile["palette"])
    return (f"{subject}. Style: {profile['visual_style']}. Color palette: {pal}. {safe}"
            "No text, no letters, no words, no logos, no watermark, no real people.")


def _procedural(title, profile, size, idx, seed, out):
    """Offline fallback card: palette gradient + shapes + title. Same palette => still consistent."""
    w, h = size
    c1, c2 = (hex_rgb(c) for c in profile["palette"])
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)))
    rng = random.Random(seed * 100 + idx)
    over = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for _ in range(7):
        r = rng.randint(min(w, h) // 10, min(w, h) // 3)
        x, y = rng.randint(0, w), rng.randint(0, h)
        od.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, rng.randint(25, 70)))
    img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    d = ImageDraw.Draw(img)
    font = get_font(min(w, h) // 9)
    words, lines, cur = title.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if d.textlength(trial, font=font) > w * 0.8 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = trial
    lines.append(cur)
    y = h // 2 - len(lines) * font.size // 2
    for ln in lines:
        d.text(((w - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill="white")
        y += int(font.size * 1.25)
    img.save(out)


def get_image(scene, profile, size, seed, idx, trace, minor):
    prompt = build_prompt(scene["image_prompt"], profile, minor)
    path = cache_file("img", key_of(prompt, size, seed), "png")
    if path.exists():
        return path, "cache"

    if not config.OFFLINE:
        def fetch():
            # With a free key (enter.pollinations.ai) use the authenticated gateway;
            # without one fall back to the old anonymous endpoint (heavily throttled).
            if config.POLLINATIONS_API_KEY:
                url = f"https://gen.pollinations.ai/image/{quote(prompt, safe='')}"
                headers = {"Authorization": f"Bearer {config.POLLINATIONS_API_KEY}"}
            else:
                url = f"https://image.pollinations.ai/prompt/{quote(prompt, safe='')}"
                headers = {}
            r = requests.get(url, headers=headers,
                             params={"width": size[0], "height": size[1], "seed": seed,
                                     "nologo": "true", "model": "flux"}, timeout=90)
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image"):
                raise ValueError("response was not an image")
            return Image.open(io.BytesIO(r.content)).convert("RGB")

        try:
            img = retry(fetch, tries=3, base=2, trace=trace, label=f"image {idx + 1}")
            ImageOps.fit(img, size, Image.LANCZOS).save(path)
            return path, "pollinations"
        except Exception as e:  # noqa: BLE001
            trace.log("visuals", f"scene {idx + 1}: image API failed ({str(e)[:70]}), using procedural card")

    # Fallback card goes to a separate file so it is never mistaken for a real cached image
    fallback = path.with_name(path.stem + "_fallback.png")
    _procedural(scene["title"], profile, size, idx, seed, fallback)
    return fallback, "procedural-fallback"