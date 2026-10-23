"""Step 3: voiceover. Runs BEFORE timing is decided: scene duration = real audio length."""
import asyncio
import concurrent.futures
import json
import re
import wave

from . import config
from .util import cache_file, key_of, retry, run_ffmpeg

VOICES = {
    "en": {"female": "en-IN-NeerjaNeural", "male": "en-IN-PrabhatNeural"},
    "hi": {"female": "hi-IN-SwaraNeural", "male": "hi-IN-MadhurNeural"},
    "kn": {"female": "kn-IN-SapnaNeural", "male": "kn-IN-GaganNeural"},
}
PAD = 0.35  # silence appended to every scene so scenes breathe


def apply_lexicon(text):
    """Fix known TTS mispronunciations using pronunciations.json."""
    p = config.ROOT / "pronunciations.json"
    if not p.exists():
        return text
    for word, spoken in json.loads(p.read_text(encoding="utf-8")).items():
        if word.startswith("_"):
            continue
        text = re.sub(rf"\b{re.escape(word)}\b", spoken, text, flags=re.I)
    return text


def rate_for(pace_wpm):
    """Map the audience's target pace to an edge-tts rate (150 wpm = normal)."""
    pct = round((pace_wpm / 150 - 1) * 100)
    return f"{max(-25, min(30, pct)):+d}%"


async def _edge(text, voice, rate, out):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


def _run_async(factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with concurrent.futures.ThreadPoolExecutor(1) as ex:  # inside Streamlit etc.
        return ex.submit(lambda: asyncio.run(factory())).result()


def wav_duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def _silent_wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * int(44100 * seconds))


def synth_scene(text, out_wav, profile, lang, trace):
    spoken = apply_lexicon(text)
    voices = VOICES.get(lang, VOICES["en"])
    voice = voices.get(profile.get("voice_gender", "female"), voices["female"])
    rate = rate_for(profile.get("pace_wpm", 150))
    mp3 = cache_file("tts", key_of(spoken, voice, rate), "mp3")
    engine = "cache" if mp3.exists() and mp3.stat().st_size > 0 else None

    if not engine and not config.OFFLINE:
        try:
            retry(lambda: _run_async(lambda: _edge(spoken, voice, rate, mp3)), tries=2, trace=trace, label="edge-tts")
            engine = "edge-tts"
        except Exception as e:  # noqa: BLE001
            mp3.unlink(missing_ok=True)
            trace.log("voice", f"edge-tts failed ({str(e)[:70]}), trying gTTS")
            try:
                from gtts import gTTS
                retry(lambda: gTTS(spoken, lang=lang).save(str(mp3)), tries=2, trace=trace, label="gTTS")
                engine = "gTTS"
            except Exception as e2:  # noqa: BLE001
                mp3.unlink(missing_ok=True)
                trace.log("voice", f"gTTS failed too ({str(e2)[:70]})")

    if engine:
        try:
            run_ffmpeg(["-i", mp3, "-ar", "44100", "-ac", "1", "-af", f"apad=pad_dur={PAD}", out_wav])
        except Exception as e:  # noqa: BLE001
            mp3.unlink(missing_ok=True)
            trace.log("voice", f"audio decode failed ({str(e)[:70]})")
            engine = None

    if not engine:  # last resort: silent track timed from the target pace, so the video still builds
        words = max(1, len(text.split()))
        _silent_wav(out_wav, words / (profile.get("pace_wpm", 150) / 60) + PAD)
        engine = "silent-fallback"
        trace.log("voice", "no TTS available: using a silent track timed from the target pace")

    return {"duration": wav_duration(out_wav), "engine": engine, "voice": voice, "rate": rate}
