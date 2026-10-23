"""Steps 1 + 4: script analysis and audience adaptation, with a critic loop and an offline fallback."""
import json
import math
import re

from . import config, llm

LANG_NAMES = {"en": "English", "hi": "Hindi", "kn": "Kannada"}

# Unicode block of each non-English script, used to check the LLM really wrote in that language
SCRIPT_RANGES = {"hi": (0x0900, 0x097F), "kn": (0x0C80, 0x0CFF)}

PRESETS = {
    "child": dict(
        tone="playful, encouraging", vocab_level="simple words, short sentences", grade_target=5,
        pace_wpm=125, voice_gender="female", music_mood="upbeat, light",
        visual_style="bright flat vector illustration, friendly cartoon, rounded shapes, saturated colors",
        palette=["#FFB703", "#219EBC"]),
    "executive": dict(
        tone="concise, authoritative", vocab_level="professional, outcome-focused", grade_target=12,
        pace_wpm=160, voice_gender="male", music_mood="calm, understated",
        visual_style="minimal modern corporate photography, muted tones, clean composition, soft depth of field",
        palette=["#1D3557", "#A8DADC"]),
    "general": dict(
        tone="friendly, clear", vocab_level="plain everyday English", grade_target=8,
        pace_wpm=145, voice_gender="female", music_mood="neutral, warm",
        visual_style="clean modern illustration, soft colors, simple composition",
        palette=["#2A9D8F", "#E9C46A"]),
}


def preset_name(audience):
    a = audience.lower()
    if any(k in a for k in ("child", "kid", "school", "student", "teen", "age 10", "aged 10", "grade")):
        return "child"
    if any(k in a for k in ("executive", "ceo", "cxo", "manager", "board", "leader", "professional", "senior")):
        return "executive"
    return "general"


def is_minor_audience(audience):
    return preset_name(audience) == "child"


def in_language(data, language):
    """True if the narration is mostly written in the target script (always True for English)."""
    rng = SCRIPT_RANGES.get(language)
    if not rng:
        return True
    text = " ".join(s["narration"] for s in data["scenes"])
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    return sum(rng[0] <= ord(c) <= rng[1] for c in letters) / len(letters) >= 0.5


# ---------------------------------------------------------------- LLM path
SYSTEM_ADAPT = "You are a video scriptwriter and audience-adaptation engine. Reply with valid JSON only."


def adapt_prompt(topic, script, audience, language, target_seconds, feedback):
    fb = f"\nA reviewer rejected your previous attempt. Fix this: {feedback}\n" if feedback else ""
    name = LANG_NAMES.get(language, "English")
    lang_rule = (f"\n- Write ALL narration and scene titles in {name}, in its native script. "
                 f"Do not write them in English. Only image_prompt and visual_style stay in English."
                 if language != "en" else "")
    return f"""TOPIC: {topic}
AUDIENCE: {audience}
OUTPUT LANGUAGE: {LANG_NAMES.get(language, 'English')}
TARGET VIDEO LENGTH: {target_seconds} seconds
ORIGINAL SCRIPT:
{script}
{fb}
Task: (1) profile the audience, (2) adapt the script for them, (3) split it into scenes.
Rules:
- Preserve every factual claim of the original. You may reword, reorder lightly and add a short hook or recap. Never invent statistics.
- Choose pace_wpm (100-180). Total narration words must be about pace_wpm * {target_seconds} / 60 (within 15%). If the script is short, expand with a hook/recap; if long, tighten it.
- 4 to 8 scenes, each 1-3 short sentences.{lang_rule}
- Vocabulary, sentence length, tone and pacing must clearly suit the audience.
- image_prompt: describe ONLY the subject and composition of one concrete visual. No text, letters, logos, brands or real people. Safe for all ages.
- visual_style: ONE style string reused for every scene so the video looks consistent.
- palette: two hex colors like "#1D3557".
Return JSON exactly in this shape:
{{"profile": {{"tone": "", "vocab_level": "", "grade_target": 8, "pace_wpm": 140, "visual_style": "", "palette": ["#000000", "#ffffff"], "voice_gender": "female", "music_mood": ""}},
 "scenes": [{{"title": "max 4 words", "narration": "", "image_prompt": ""}}]}}"""


SYSTEM_CRITIC = "You are a strict editor reviewing audience fit. Reply with valid JSON only."


def critic_prompt(audience, original, data):
    adapted = "\n".join(f"{i + 1}. {s['narration']}" for i, s in enumerate(data["scenes"]))
    return f"""AUDIENCE: {audience}
ORIGINAL SCRIPT:
{original}

ADAPTED NARRATION:
{adapted}

Judge: would this audience understand it and feel it was written for them (vocabulary, tone, length of sentences)?
Did the adaptation keep every factual claim of the original, with nothing invented?
Return JSON: {{"audience_fit": 1-10, "facts_preserved": true/false, "issues": ["..."], "fix": "one-sentence instruction to improve it"}}"""


def validate(data, audience):
    base = dict(PRESETS[preset_name(audience)])
    prof = data.get("profile") or {}
    base.update({k: v for k, v in prof.items() if v not in (None, "", [])})
    try:
        base["pace_wpm"] = int(max(100, min(180, float(base["pace_wpm"]))))
    except (TypeError, ValueError):
        base["pace_wpm"] = PRESETS[preset_name(audience)]["pace_wpm"]
    try:
        base["grade_target"] = int(base["grade_target"])
    except (TypeError, ValueError):
        base["grade_target"] = PRESETS[preset_name(audience)]["grade_target"]
    pal = base.get("palette")
    ok = isinstance(pal, list) and len(pal) >= 2 and all(re.fullmatch(r"#[0-9a-fA-F]{6}", str(c)) for c in pal[:2])
    base["palette"] = [str(c) for c in pal[:2]] if ok else PRESETS[preset_name(audience)]["palette"]
    base["voice_gender"] = "male" if str(base.get("voice_gender", "")).lower().startswith("m") else "female"

    # Pace and voice are set by the audience type (not the LLM) so the Audience Diff is deterministic:
    # children get a slower, female voice; executives a faster, male voice.
    preset = PRESETS[preset_name(audience)]
    base["pace_wpm"] = preset["pace_wpm"]
    base["voice_gender"] = preset["voice_gender"]

    scenes = []
    for s in data.get("scenes") or []:
        n = str(s.get("narration", "")).strip()
        if n:
            scenes.append({"title": str(s.get("title") or " ".join(n.split()[:3])),
                           "narration": n,
                           "image_prompt": str(s.get("image_prompt") or n)})
    if not scenes:
        raise ValueError("LLM returned no scenes")
    return {"profile": base, "scenes": scenes[:8]}


def _passes(verdict):
    return (verdict.get("audience_fit") or 0) >= 7 and verdict.get("facts_preserved", True)


# ---------------------------------------------------------------- offline path
SIMPLE = {"utilize": "use", "approximately": "about", "commence": "start", "purchase": "buy",
          "additional": "more", "consumption": "use", "significant": "big", "ensure": "make sure",
          "individuals": "people", "conserve": "save", "numerous": "many", "reduce": "cut",
          "essential": "important", "efficiently": "well", "instead of": "rather than"}
FILLERS = re.compile(r"\b(really|very|just|quite|simply)\s+", re.I)


def _sentences(script):
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", script.strip()) if p.strip()]


def _split_long(s, limit):
    if len(s.split()) <= limit:
        return [s]
    commas = [m.start() for m in re.finditer(r",\s", s)]
    if not commas:
        return [s]
    mid = len(s) / 2
    i = min(commas, key=lambda c: abs(c - mid))
    first, second = s[:i].rstrip(",") + ".", s[i + 1:].strip()
    return [first, second[:1].upper() + second[1:]]


def heuristic(script, audience):
    """Rule-based fallback so the pipeline never dies when the LLM is unavailable."""
    kind = preset_name(audience)
    sents = _sentences(script)
    out = []
    for s in sents:
        if kind == "child":
            for k, v in SIMPLE.items():
                s = re.sub(rf"\b{k}\b", v, s, flags=re.I)
            out.extend(_split_long(s, 14))
        elif kind == "executive":
            s = FILLERS.sub("", s)
            s = re.sub(r"\bbecause\b", "since", s, flags=re.I)
            out.append(s)
        else:
            out.append(s)
    if kind == "child" and out:
        out[0] = "Hey friends! " + out[0]
        out.append("Now you know how to help. Let's do it!")
    if kind == "executive" and out:
        out.append("The takeaway: small, consistent actions compound into measurable impact.")
    per = max(1, math.ceil(len(out) / 8))
    scenes = []
    for i in range(0, len(out), per):
        n = " ".join(out[i:i + per])
        scenes.append({"title": " ".join(n.split()[:3]), "narration": n,
                       "image_prompt": f"a simple scene that illustrates: {n[:110]}"})
    return {"profile": dict(PRESETS[kind]), "scenes": scenes}


# ---------------------------------------------------------------- translation (Hindi / Kannada)
SYSTEM_TRANSLATE = "You are a professional translator for video voiceovers. Reply with valid JSON only."


def translate_prompt(narrations, language, audience, feedback):
    name = LANG_NAMES.get(language, language)
    fb = f"\nYour previous answer was rejected. Fix this: {feedback}\n" if feedback else ""
    return f"""Translate these {len(narrations)} voiceover lines into {name}.
AUDIENCE: {audience} (keep the same tone and vocabulary level)
Rules:
- Write in {name} using its native script only. Natural spoken style, same meaning. Do not add or remove facts.
- Keep numbers. Return exactly {len(narrations)} items, in the same order.{fb}
LINES (JSON array):
{json.dumps(narrations, ensure_ascii=False)}
Return JSON exactly in this shape: {{"narrations": ["...", "..."]}}"""


def translate_scenes(data, language, audience, trace, tries=3):
    """Translate only the narration lines. Returns new data, or None if it could not be done.
    Unusable replies are removed from the cache so they are never reused."""
    name = LANG_NAMES.get(language, language)
    narrs = [s["narration"] for s in data["scenes"]]
    feedback = ""
    for _ in range(tries):
        prompt = translate_prompt(narrs, language, audience, feedback)
        try:
            raw = llm.call_json(prompt, SYSTEM_TRANSLATE, trace, "translate")
        except Exception as e:  # noqa: BLE001  (network errors were already retried inside call_json)
            trace.log("translate", f"translation call failed ({str(e)[:100]})")
            return None
        out = raw.get("narrations") if isinstance(raw, dict) else None
        if not (isinstance(out, list) and len(out) == len(narrs) and all(isinstance(x, str) and x.strip() for x in out)):
            llm.forget(prompt, SYSTEM_TRANSLATE)
            feedback = f"Return exactly {len(narrs)} non-empty strings in a JSON array under the key narrations."
            trace.log("translate", "reply had the wrong shape; retrying")
            continue
        cand = {**data, "scenes": [{**s, "narration": t.strip()} for s, t in zip(data["scenes"], out)]}
        if in_language(cand, language):
            trace.log("translate", f"translated {len(out)} scenes into {name}")
            return cand
        llm.forget(prompt, SYSTEM_TRANSLATE)
        feedback = f"The lines must be in {name} native script, not English or romanized."
        trace.log("translate", f"reply was not in {name} script; retrying")
    return None


# ---------------------------------------------------------------- entry point
def adapt(topic, script, audience, language, target_seconds, trace, max_rounds=2):
    """Returns (data, verdict). Tries LLM + critic loop; degrades to heuristic on any failure.

    For Hindi/Kannada: adapt in English first (short, cheap, critic checks the facts), then translate only
    the narration lines in one small call. verdict['translated'] tells the caller whether that worked."""
    if language != "en" and llm.available():
        data, verdict = adapt(topic, script, audience, "en", target_seconds, trace, max_rounds)
        if verdict.get("source") == "llm":
            translated = translate_scenes(data, language, audience, trace)
            if translated:
                return translated, {**verdict, "translated": True}
        return data, {**verdict, "translated": False}

    if llm.available():
        feedback, best, best_score = "", None, -1
        for rnd in range(max_rounds + 1):
            try:
                raw = llm.call_json(adapt_prompt(topic, script, audience, language, target_seconds, feedback),
                                    SYSTEM_ADAPT, trace, "adapt")
                data = validate(raw, audience)
            except Exception as e:  # noqa: BLE001
                trace.log("adapt", f"LLM adapt failed ({str(e)[:100]})")
                break

            # Language check: if the model wrote English (or anything else) instead of the requested
            # language, skip the critic and ask for a rewrite.
            if not in_language(data, language):
                name = LANG_NAMES.get(language, language)
                if rnd < max_rounds:
                    trace.log("adapt", f"narration is not in {name}; asking for a rewrite")
                    feedback = (f"Your narration was not written in {name}. Write ALL narration and titles "
                                f"in {name} using its native script. Only image_prompt stays in English.")
                    continue
                trace.log("adapt", f"WARNING: narration still not in {name} after {max_rounds + 1} tries; "
                                   "keeping it, the voice and text may not match")

            try:
                verdict = llm.call_json(critic_prompt(audience, script, data), SYSTEM_CRITIC, trace, "critic")
            except Exception as e:  # noqa: BLE001
                trace.log("critic", f"critic unavailable ({str(e)[:80]}); accepting draft")
                return data, {"source": "llm", "audience_fit": None}
            score = verdict.get("audience_fit") or 0
            trace.log("critic", f"round {rnd + 1}: fit={score}/10, facts_preserved={verdict.get('facts_preserved')}",
                      issues=verdict.get("issues"))
            verdict["source"] = "llm"
            if score > best_score:
                best, best_score = (data, verdict), score
            if _passes(verdict):
                break
            feedback = (verdict.get("fix") or "") + " " + "; ".join(map(str, verdict.get("issues") or []))
            trace.log("adapt", "critic asked for a rewrite" if rnd < max_rounds else "max rounds reached, keeping best draft")
        if best:
            return best
    trace.log("adapt", "using offline rule-based adapter (degraded mode, lower quality)")
    return heuristic(script, audience), {"source": "heuristic", "audience_fit": None}