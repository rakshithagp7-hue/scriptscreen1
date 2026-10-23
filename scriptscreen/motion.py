"""Real AI video clips (Magic Hour text-to-video).

Rules this module follows:
  - never fatal: any failure returns None and the pipeline uses the Ken Burns animation instead
  - cached: the same prompt is never paid for twice
  - credit-aware: checks your balance first and skips the call if it can't cover a clip
"""
import shutil

import requests

from . import config
from .util import cache_file, key_of

CLIP_SECONDS = 5      # length of one generated clip
CLIP_COST = 120       # credits per 5 s clip at ltx-2.5 / 480p (measured on the test run)
ASPECT = {"horizontal": "16:9", "vertical": "9:16", "square": "1:1"}
MOTION_HINT = ("Smooth natural motion: moving water and objects, slow cinematic camera push-in, "
               "one continuous shot, no cuts.")


def available():
    return bool(config.MAGIC_HOUR_API_KEY) and not config.OFFLINE and config.AI_CLIPS_MAX > 0


def credits():
    """Remaining Magic Hour credits, or None if the balance can't be read."""
    try:
        r = requests.get("https://api.magichour.ai/v1/account",
                         headers={"Authorization": f"Bearer {config.MAGIC_HOUR_API_KEY}"}, timeout=20)
        r.raise_for_status()
        return int(r.json().get("credits"))
    except Exception:  # noqa: BLE001
        return None


def make_clip(prompt, fmt, trace):
    """Returns the path of a ~5 s mp4 for this prompt, or None (caller falls back to Ken Burns)."""
    aspect = ASPECT.get(fmt, "16:9")
    path = cache_file("aiclip", key_of(prompt, aspect, config.MAGIC_HOUR_MODEL, config.MAGIC_HOUR_RES), "mp4")
    if path.exists() and path.stat().st_size > 0:
        trace.log("motion", "AI clip cache hit (0 credits)")
        return path

    balance = credits()
    if balance is not None and balance < CLIP_COST:
        trace.log("motion", f"only {balance} credits left (a clip needs {CLIP_COST}); using Ken Burns instead")
        return None

    tmp = config.CACHE_DIR / f"{path.stem}_dl"
    try:
        from magic_hour import Client
        tmp.mkdir(parents=True, exist_ok=True)
        trace.log("motion", f"generating AI clip (balance={balance}); this takes a minute or two...")
        r = Client(token=config.MAGIC_HOUR_API_KEY).v1.text_to_video.generate(
            end_seconds=CLIP_SECONDS,
            aspect_ratio=aspect,
            style={"prompt": prompt},
            name="ScriptToScreen scene",
            model=config.MAGIC_HOUR_MODEL,
            resolution=config.MAGIC_HOUR_RES,
            wait_for_completion=True,
            download_outputs=True,
            download_directory=str(tmp),
        )
        if r.status != "complete" or not r.downloaded_paths:
            err = getattr(getattr(r, "error", None), "message", "") or r.status
            raise RuntimeError(err)
        shutil.move(str(r.downloaded_paths[0]), str(path))
        trace.log("motion", f"AI clip ready ({r.credits_charged} credits used)")
        return path
    except Exception as e:  # noqa: BLE001
        trace.log("motion", f"AI clip failed ({str(e)[:90]}); using Ken Burns instead")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
