"""CLI:  python run.py --sample samples/water.json   (add --out prerendered/water to save a fallback)"""
import argparse
import json
from pathlib import Path

from scriptscreen import config, metrics, pipeline


def main():
    ap = argparse.ArgumentParser(description="ScriptToScreen: Audience Diff")
    ap.add_argument("--sample", help="path to a sample JSON (topic, script, audiences)")
    ap.add_argument("--topic")
    ap.add_argument("--script-file")
    ap.add_argument("--audiences", nargs="+")
    ap.add_argument("--lang", default=None, choices=["en", "hi", "kn"])
    ap.add_argument("--format", default="horizontal", choices=list(config.FORMATS))
    ap.add_argument("--target", type=int, default=config.TARGET_SECONDS, help="target seconds (30-60)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--offline", action="store_true", help="no network at all (silent video, procedural visuals)")
    a = ap.parse_args()

    if a.offline:
        config.OFFLINE = True
    if a.sample:
        s = json.loads(Path(a.sample).read_text(encoding="utf-8"))
        topic, script, auds, lang = s["topic"], s["script"], s["audiences"], s.get("language", "en")
    else:
        if not (a.topic and a.script_file and a.audiences):
            ap.error("give --sample OR --topic, --script-file and --audiences")
        topic, script = a.topic, Path(a.script_file).read_text(encoding="utf-8")
        auds, lang = a.audiences, "en"

    res = pipeline.compare(topic, script, auds, out_root=a.out, language=a.lang or lang,
                           fmt=a.format, target_seconds=a.target)
    print("\n" + metrics.compare_markdown({k: v["scorecard"] for k, v in res.items()}))
    for k, v in res.items():
        print(f"\n{k}: {v['video'] or 'NO VIDEO (asset package only)'}  warnings={v['warnings']}")


if __name__ == "__main__":
    main()
