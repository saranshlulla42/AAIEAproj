"""A small demonstration interface; run with streamlit run app.py."""
from pathlib import Path
import json

import streamlit as st

from storyclip.agent import choose
from storyclip.candidates import flag_repeated_entries, propose
from storyclip.detectors import scan
from storyclip.media import probe, render


ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Valorant StoryClip", page_icon="🎮", layout="wide")
st.title("Valorant StoryClip")
st.write("Turn gameplay into a vertical encounter highlight or a chronological match story.")
videos = sorted([*ROOT.glob("*.webm"), *ROOT.glob("*.mp4"), *ROOT.glob("*.mkv")])
if not videos:
    st.info("Place your gameplay recording in the project folder, then refresh.")
    st.stop()
video = st.selectbox("Gameplay recording", videos, format_func=lambda p: p.name)
info = probe(video)
config = json.loads((ROOT / "hud_config.json").read_text())
out = ROOT / "runs" / "demo"
if (out / "scan.json").exists() and json.loads((out / "scan.json").read_text())["manifest"]["source"] != info:
    from storyclip.timeline import fingerprint
    out = ROOT / "runs" / ("source-" + fingerprint(info)[:12])
st.caption(f"{info['duration']/60:.1f} minutes · {info['width']} × {info['height']} · Tracking {config['player_name']}")
st.info("The HUD detector is calibrated to the supplied s0m recording. Review detected events before trusting the clip's description.")
clip_mode = st.radio("Video mode", ["Moment Highlight", "Match Story"], horizontal=True)
if clip_mode == "Match Story":
    from storyclip.story_ui import show_story
    show_story(ROOT, video, info, config, out)
    st.stop()
left, right = st.columns([2, 1])
with left:
    st.subheader("1. Find candidate encounters")
    if st.button("Scan gameplay", type="primary"):
        try:
            with st.status("Scanning the HUD. The first scan may take several minutes; matching scans are cached.", expanded=True) as status:
                result = scan(video, config, out)
                result["events"] = flag_repeated_entries(result["events"])
                candidates = propose(result["events"], info["duration"])
                (out / "candidates.json").write_text(json.dumps(candidates, indent=2))
                status.update(label=f"Found {len(candidates)} candidate encounters", state="complete")
        except Exception as error:
            st.error(str(error))
    result = json.loads((out / "scan.json").read_text()) if (out / "scan.json").exists() else None
    if result and (result["manifest"]["source"] != info or result["manifest"]["config"] != config):
        st.warning("Existing scan belongs to another recording or HUD configuration. Scan the selected video first.")
        result = None
    if result:
        result["events"] = flag_repeated_entries(result["events"])
    candidates = propose(result["events"], info["duration"]) if result else []
    if result:
        a, b, c = st.columns(3)
        a.metric("Detected events", len(result["events"]))
        b.metric("Candidates", len(candidates))
        c.metric("Scan time", f"{result['metrics']['elapsed_s']/60:.1f} min")
        st.dataframe([{k: c[k] for k in ["id", "start_s", "end_s", "cluster_kills", "low_health_kills", "score"]}
                      for c in candidates], hide_index=True, width="stretch")
        with st.expander("Inspect event records and HUD evidence"):
            st.dataframe([{k: e[k] for k in ["id", "time_s", "victim", "displayed_hp_before", "observations", "status"]}
                          for e in result["events"]], hide_index=True, width="stretch")
            if result["events"]:
                event = st.selectbox("Evidence to inspect", result["events"], format_func=lambda e: f"{e['id']} · {e['time_s']:.1f}s · {e['victim']}")
                st.image(event["evidence_path"], caption="Saved kill-feed crop; inspect attribution and OCR errors.")
    st.subheader("2. Choose and render a clip")
    mode = st.radio("Selection method", ["Pi subscription agent", "Event baseline"], horizontal=True)
    if st.button("Create highlight", disabled=not candidates):
        try:
            with st.status("Selecting a candidate and rendering the clip…", expanded=True) as status:
                if mode == "Pi subscription agent":
                    plan = choose(candidates, result["events"], result["health"], info["duration"], out, video=video)
                    filename = "highlight.mp4"
                else:
                    candidate = candidates[0]
                    plan = {"candidate_id": candidate["id"], "start_s": candidate["start_s"], "end_s": candidate["end_s"],
                            "mode": "event_baseline", "needs_human_review": True}
                    (out / "baseline_plan.json").write_text(json.dumps(plan, indent=2))
                    filename = "baseline.mp4"
                layout = json.loads((ROOT / "portrait_layout.json").read_text())
                actual = render(video, plan["start_s"], plan["end_s"], out / filename, config=layout)
                (out / "render_metrics.json").write_text(json.dumps(actual, indent=2))
                st.session_state["output"] = filename
                status.update(label="Highlight is ready for review", state="complete")
        except Exception as error:
            st.error(str(error))
with right:
    st.subheader("Preview")
    filename = st.session_state.get("output", "highlight.mp4")
    output = out / filename
    if output.exists() and result:
        st.video(str(output))
        st.download_button("Download MP4", output.read_bytes(), file_name=filename, mime="video/mp4")
        plan_path = out / ("edit_plan.json" if filename == "highlight.mp4" else "baseline_plan.json")
        if plan_path.exists():
            plan = json.loads(plan_path.read_text())
            st.write(f"Source interval: {plan['start_s']:.1f}–{plan['end_s']:.1f} seconds")
            st.write(plan.get("reason", "Highest-scoring event candidate with fixed boundaries."))
        st.caption("Watch the full clip to verify the outcome, framing, and audio sync before posting.")
    else:
        st.caption("Your exported clip will appear here.")
    trace_path = out / "agent_trace.json"
    if trace_path.exists() and result:
        with st.expander("Agent decisions and tool results"):
            st.json(json.loads(trace_path.read_text()))
