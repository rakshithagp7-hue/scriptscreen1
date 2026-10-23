"""Makes 'measurable differences between audiences' concrete."""
import re


def _syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def flesch_kincaid(text):
    words = re.findall(r"[A-Za-z']+", text)
    sents = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if not words or not sents:
        return None
    syl = sum(_syllables(w) for w in words)
    return round(0.39 * len(words) / len(sents) + 11.8 * syl / len(words) - 15.59, 1)


def scorecard(profile, scenes, infos, verdict, lang, fmt):
    text = " ".join(s["narration"] for s in scenes)
    words = len(text.split())
    sents = len([s for s in re.split(r"[.!?।]+", text) if s.strip()]) or 1
    total = sum(i["duration"] for i in infos)
    spoken = total - 0.35 * len(infos)
    return {
        "reading_grade": flesch_kincaid(text) if lang == "en" else "n/a",
        "words_per_sentence": round(words / sents, 1),
        "total_words": words,
        "speaking_pace_wpm": round(words / (spoken / 60)) if spoken > 0 else None,
        "scenes": len(scenes),
        "avg_scene_seconds": round(total / len(scenes), 1),
        "duration_seconds": round(total, 1),
        "tone": profile.get("tone"),
        "visual_style": profile.get("visual_style"),
        "palette": " / ".join(profile.get("palette", [])),
        "voice": infos[0]["voice"] if infos else "",
        "tts_rate": infos[0]["rate"] if infos else "",
        "music_mood_suggested": profile.get("music_mood"),
        "critic_fit_score": verdict.get("audience_fit"),
        "adapter": verdict.get("source"),
        "format": fmt,
    }


ROWS = [
    ("Reading grade (Flesch-Kincaid)", "reading_grade"),
    ("Words per sentence", "words_per_sentence"),
    ("Speaking pace (words/min)", "speaking_pace_wpm"),
    ("Scenes", "scenes"),
    ("Avg scene length (s)", "avg_scene_seconds"),
    ("Video length (s)", "duration_seconds"),
    ("Tone", "tone"),
    ("Visual style", "visual_style"),
    ("Palette", "palette"),
    ("Voice", "voice"),
    ("TTS rate", "tts_rate"),
    ("Music mood (suggested)", "music_mood_suggested"),
    ("Critic audience-fit /10", "critic_fit_score"),
    ("Adapter used", "adapter"),
]


def compare_rows(cards):
    return [{"Metric": label, **{name: str(card.get(key, "")) for name, card in cards.items()}} for label, key in ROWS]


def compare_markdown(cards):
    names = list(cards)
    out = ["| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for r in compare_rows(cards):
        out.append(f"| {r['Metric']} | " + " | ".join(str(r[n]) for n in names) + " |")
    return "\n".join(out)
