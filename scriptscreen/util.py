import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from . import config


class Trace:
    """Decision log: every step, retry and fallback is recorded (shown in UI, saved as trace.json)."""

    def __init__(self, label=""):
        self.label = label
        self.t0 = time.time()
        self.events = []

    def log(self, step, msg, **data):
        self.events.append({"t": round(time.time() - self.t0, 1), "step": step, "msg": msg, **data})
        tag = f"{self.label}:{step}" if self.label else step
        print(f"  [{tag}] {msg}")

    def save(self, path):
        Path(path).write_text(json.dumps(self.events, indent=2, ensure_ascii=False), encoding="utf-8")


def key_of(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:20]


def cache_file(kind, key, ext):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.CACHE_DIR / f"{kind}_{key}.{ext}"


def retry(fn, tries=3, base=1.5, trace=None, label=""):
    """Exponential backoff. Raises the last error if all attempts fail."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if trace:
                trace.log("retry", f"{label} attempt {i + 1}/{tries} failed: {str(e)[:120]}")
            if i < tries - 1:
                time.sleep(base * (2 ** i))
    raise last


def ffmpeg_exe():
    """Bundled ffmpeg from imageio-ffmpeg, so no system install is needed."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("ffmpeg not found. Run: pip install imageio-ffmpeg")
        return exe


def run_ffmpeg(args):
    p = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", *map(str, args)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-600:])
