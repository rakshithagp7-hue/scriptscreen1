"""Streamlit UI:  streamlit run app.py"""
import json
from pathlib import Path
 
import streamlit as st
 
from scriptscreen import config, llm, metrics, motion, pipeline
 
st.set_page_config(page_title="ScriptToScreen: Audience Diff", layout="wide")
st.title("ScriptToScreen: Audience Diff")
st.caption("One script, two audiences. Watch what changes: wording, pace, voice, visuals.")
 
sample = json.loads((config.ROOT / "samples" / "water.json").read_text(encoding="utf-8"))
 
with st.sidebar:
    st.header("Settings")
    lang = st.selectbox("Language", ["en", "hi", "kn"], help="Captions are English-only (Indic fonts need extra setup).")
    fmt = st.selectbox("Format", list(config.FORMATS), help="horizontal=YouTube, vertical=Reels/Shorts, square=LinkedIn")
    target = st.slider("Target length (s)", config.MIN_SECONDS, config.MAX_SECONDS, config.TARGET_SECONDS)
    config.OFFLINE = st.toggle("Offline mode (no network)", value=config.OFFLINE,
                               help="Silent video + procedural visuals. Last-resort demo fallback.")
    use_ai = st.toggle("AI video clip in scene 1 (uses Magic Hour credits)", value=False,
                       help="Off = every scene uses the free zoom/pan animation. On = scene 1 of each video is a "
                            "real generated clip (about 120 credits per clip; cached clips cost nothing).")
    config.AI_CLIPS_MAX = 1 if use_ai else 0
    st.write("LLM:", "✅ connected" if llm.available() else "⚠️ none (rule-based adapter will be used)")
    if use_ai and motion.available():
        bal = motion.credits()
        st.write("Magic Hour credits:", bal if bal is not None else "unknown")
 
tab_live, tab_pre = st.tabs(["Generate", "Pre-rendered fallback"])
 
 
def show(results):
    cols = st.columns(len(results))
    for col, (aud, r) in zip(cols, results.items()):
        with col:
            st.subheader(aud)
            if r["video"]:
                st.video(str(r["video"]))
                st.download_button("Download MP4", Path(r["video"]).read_bytes(), file_name=f"{Path(r['dir']).name}.mp4",
                                   key=f"dl_{aud}")
            else:
                st.warning("Video encode failed. Asset package saved in " + str(r["dir"]))
            for w in r["warnings"]:
                st.warning(w)
            with st.expander("Adapted narration"):
                for i, s in enumerate(r["scenes"]):
                    st.write(f"**{i + 1}.** {s['narration']}")
            with st.expander("Decision log (agent reasoning)"):
                st.json(r["trace"])
    st.subheader("Audience Diff scorecard")
    st.table(metrics.compare_rows({a: r["scorecard"] for a, r in results.items()}))
 
 
with tab_live:
    topic = st.text_input("Topic", sample["topic"])
    script = st.text_area("Script (5-10 lines)", sample["script"], height=200)
    c1, c2 = st.columns(2)
    a1 = c1.text_input("Audience A", sample["audiences"][0])
    a2 = c2.text_input("Audience B", sample["audiences"][1])
    if st.button("Generate both videos", type="primary"):
        with st.status("Running pipeline (adapt → voice → visuals → assemble)...", expanded=True) as status:
            res = pipeline.compare(topic, script, [a1, a2], language=lang, fmt=fmt, target_seconds=target)
            status.update(label="Done", state="complete")
        st.session_state["results"] = res
    if "results" in st.session_state:
        show(st.session_state["results"])
 
with tab_pre:
    root = config.ROOT / "prerendered"
    sets = [d for d in sorted(root.glob("*")) if d.is_dir()] if root.exists() else []
    if not sets:
        st.info("Nothing here yet. Run:  python run.py --sample samples/water.json --out prerendered/water")
    for d in sets:
        st.markdown(f"### {d.name}")
        cards, cols = {}, st.columns(2)
        subs = [s for s in sorted(d.iterdir()) if (s / "video.mp4").exists()]
        for col, s in zip(cols, subs):
            col.markdown(f"**{s.name}**")
            col.video(str(s / "video.mp4"))
            cards[s.name] = json.loads((s / "scorecard.json").read_text(encoding="utf-8"))
        if cards:
            st.table(metrics.compare_rows(cards))
 

