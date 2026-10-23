# ScriptToScreen: Audience Diff

Turn **topic + script + audience** into a captioned video, and prove the audience adaptation with a
**side-by-side scorecard**: the same script rendered for two audiences (e.g. school children vs senior executives).

Works with **zero API keys** (rule-based adapter + free TTS + free image API). Add a free Gemini or Groq key for
much better adaptation.

## Quick start (GitHub Codespaces, no local install needed)

1. Push this folder to a GitHub repo → **Code → Codespaces → Create codespace**.
2. In the terminal:
   ```bash
   pip install -r requirements.txt
   cp .env.example .env        # optional: paste a GEMINI_API_KEY (free) or Groq key
   python run.py --sample samples/water.json      # CLI: two videos + comparison table
   streamlit run app.py                           # web UI (Codespaces shows an "Open in browser" popup)
   ```
No system FFmpeg needed (bundled via `imageio-ffmpeg`). Works the same on Windows/Mac/Linux.

**Before the demo, pre-render a fallback:**
```bash
python run.py --sample samples/water.json --out prerendered/water
```
The UI's "Pre-rendered fallback" tab plays these instantly if an API is slow.

## Pipeline

```
Topic + Script + Audience
   │
   ▼  [1+4] Adapter (LLM): audience profile + meaning-preserving rewrite + scenes
   │        └─ Critic (LLM): fit score + fact check → rewrite loop (max 2) ── fallback: rule-based adapter
   ▼  [3] Voiceover per scene (edge-tts → gTTS → silent track)   ← runs FIRST
   │        └─ real audio length = scene duration
   ▼  [2] One image per scene (Pollinations → procedural card)   ← one style bible + one seed
   ▼  [5] Assembly: captions burned in, synced per chunk, FFmpeg encode  (fallback: asset package)
   ▼  [6] Output: video.mp4, captions.srt, voiceover.wav, adapted.json (timecodes), scorecard.json, trace.json
```

## How it handles the known weak spots

| Weak spot in the brief | What this does |
|---|---|
| Too much for 6 h | Every step has a degraded mode, so a full demo works even if 2 APIs are down |
| API limits / latency | Disk cache (same input = zero API calls), retries with backoff, fallbacks, pre-render command |
| Circular timing (duration vs audio) | Audio is generated first; scene time = measured audio length; captions split by text length inside that |
| Visual inconsistency | One `visual_style` + palette + fixed seed appended to every image prompt (reduces drift, doesn't eliminate it) |
| Setup friction | Bundled FFmpeg, 7 pip packages, no keys required, runs in Codespaces |
| Polish contradiction | Treated as "clean and in sync", not cinematic |
| Video length conflict | Fixed to **30-60 s** (default 45); adapter gets a word budget = pace × target; a warning is logged if outside |
| Rewrite allowed? | Assumption: **yes, meaning-preserving.** The critic checks that no facts were added or lost |
| "Measurable differences" | Scorecard: Flesch-Kincaid grade, words/sentence, speaking pace, scene length, tone, style, palette, voice, TTS rate, critic score |
| Short script vs 30-90 s | Adapter expands with hook/recap or tightens, to hit the word budget |
| Child safety / rights | Minor audience → "child-friendly" prompt rule + blocked words; prompts forbid real people/logos; no music is auto-added (rights); Pollinations/AI image licensing should be checked before commercial use |
| Text in AI images / TTS mispronunciations | Prompts forbid text (captions are drawn by us); `pronunciations.json` lexicon fixes words before TTS |
| Indian languages | `--lang hi` / `kn` use Indian neural voices; captions auto-disabled for non-English (see limitations) |
| Linear pipeline | Decision log (`trace.json`, shown in UI), retry/fallback at each step, critic loop |
| Commoditized idea | The product is the **Audience Diff**: measurable proof the output changed per audience |

## Honest limitations (say this to the judges)

- Offline rule-based adapter is crude; use an LLM key for the real demo.
- Image style consistency is best-effort; characters can still differ between scenes.
- Captions are English-only; Indic scripts need a Noto font plus complex-text shaping.
- Music is only *suggested* (`music_mood`), not mixed in, to avoid copyright issues.
- Pollinations is a free public service: slow or rate-limited at times (hence cache + fallback).
- The LLM/TTS/image network paths were tested with mocks and offline mode only; run once with real keys before presenting.

## Layout
```
app.py                 Streamlit UI
run.py                 CLI
pronunciations.json    TTS lexicon
samples/               sample inputs
scriptscreen/
  adapt.py             audience profile, rewrite, critic loop, offline fallback
  voice.py             TTS + fallbacks + pacing
  visuals.py           image generation + style bible + fallback
  assemble.py          captions, SRT, FFmpeg
  metrics.py           scorecard
  pipeline.py          orchestration + compare()
  llm.py, util.py, config.py
```

## Suggested demo (8 min)
1. Problem (1) → 2. Show pre-rendered Audience Diff (2) → 3. Live run with a fresh input (2) →
4. Decision log + what happens when an API fails (1) → 5. Next steps + LinkedIn pitch (2).
