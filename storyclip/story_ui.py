"""Streamlit Match Story workflow, kept separate from Moment Highlight."""
from pathlib import Path
import json

import streamlit as st

from .detectors import scan
from .media import render_story, render_preview
from .narrative import approve_storyboard, check_approval, plan_hash, critique_passed
from .story import Beat, assisted_story, choose_story, compilation_baseline, propose_scenes, validate_storyboard
from .timeline import fingerprint, prepare_timeline
from .transcript import validate_transcript


def show_story(root: Path, video: Path, info: dict, hud: dict, out: Path) -> None:
    st.write("Summarize the match in chronological scenes, with score context and a visible finish.")
    score_config = json.loads((root/"score_config.json").read_text())
    anchor_path = out/"reviewed_anchors.json"
    use_anchors = st.checkbox("Use reviewed score anchors for this recording (assisted demo)",value=anchor_path.exists(),disabled=not anchor_path.exists())
    transcript_file = st.file_uploader("Optional speech transcript JSON with source identity",type=["json"])
    transcript = None
    invalid_transcript = False
    if transcript_file:
        try:
            data = json.loads(transcript_file.getvalue())
            if data.get("source") != info:
                raise ValueError("Transcript belongs to another recording.")
            transcript = validate_transcript(data["segments"],info["duration"],offset=data.get("offset_s",0))
        except Exception as error:
            invalid_transcript = True
            st.error(str(error))
    if st.button("Build match timeline",type="primary",disabled=invalid_transcript):
        try:
            with st.status("Discovering full-match events and score progression…",expanded=True) as status:
                result = scan(video,hud,out)
                timeline = prepare_timeline(video,result,score_config,out,anchors=anchor_path if use_anchors else None,transcript=transcript)
                scenes = propose_scenes(timeline)
                (out/"scenes.json").write_text(json.dumps(scenes,indent=2))
                status.update(label=f"Timeline ready: {len(scenes)} scene proposals",state="complete")
        except Exception as error:
            st.error(str(error))
    path = out/"timeline.json"
    if not path.exists():
        st.info("Build a timeline to discover the opening, development, and ending.")
        return
    timeline = json.loads(path.read_text())
    if timeline["source"] != info:
        st.warning("This timeline belongs to another recording. Build a timeline for the selected source.")
        return
    scenes = propose_scenes(timeline)
    a,b,c = st.columns(3)
    a.metric("Score observations",len(timeline["observations"]))
    b.metric("Scene proposals",len(scenes))
    c.metric("Final result evidence","Reviewed" if timeline["outcome_ids"] else "Unconfirmed")
    if timeline["assisted"]:
        st.caption("Assisted timeline: reviewed score anchors supplement automated OCR. Team mapping applies only to those frames.")
    if not timeline["transcript"]:
        st.caption("Original speech is preserved. Speech captions are available when a transcript is supplied.")
    with st.expander("Review score progression and source evidence"):
        st.dataframe([{k:o.get(k) for k in ["id","time_s","score","status","team_side","outcome"]} for o in timeline["observations"]],hide_index=True,width="stretch")
        observation = st.selectbox("Source frame",timeline["observations"],format_func=lambda o:f"{o['time_s']:.1f}s · {o.get('score')} · {o['status']}")
        if Path(observation["evidence_path"]).exists():
            st.image(observation["evidence_path"],caption=observation.get("review_note",observation["uncertainty"]))
        st.download_button("Download timeline",path.read_bytes(),file_name="timeline.json",mime="application/json")
    with st.expander("Scene proposals across the match"):
        st.dataframe([{k:s[k] for k in ["id","start_s","end_s","phase","possible_role","evidence_ids"]} for s in scenes],hide_index=True,width="stretch")
    st.caption("Planner: Pi / gpt-6-luna · Story draft → scene evidence → storytelling review → your approval")
    if st.button("Plan story for review",type="primary"):
        try:
            with st.status("Choosing a story thread, inspecting each scene, and checking coherence…",expanded=True) as status:
                choose_story(timeline,scenes,out,video=video,score_config=score_config,
                             scan=json.loads((out/"scan.json").read_text()),hud_config=hud,progress=st.write)
                status.update(label="Story draft ready for your review",state="complete")
                st.session_state["story_plan_path"]="storyboard_v2.json"
                st.rerun()
        except Exception as error:
            st.error(str(error))
    state_path=out/"story_v2_run_state.json"
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get("status") in {"failed","revision_requested","planning"}:
        st.info("A fresh reviewed story is still needed. Plan again to address the findings or saved feedback.")
        failed=out/"storyboard_draft.json"
        if failed.exists():
            with st.expander("Storytelling findings"):
                st.json(json.loads(failed.read_text()).get("story_review",{}))
        st.caption(state.get("error",""))
        trace_path=out/"story_v2_agent_trace.json"
        if trace_path.exists():
            with st.expander("Planning diagnostics"):
                st.json(json.loads(trace_path.read_text()))
        return
    plan_path=out/"storyboard_v2.json"
    if not plan_path.exists():
        st.info("Previous exports used phase-spanning selection. Create a new story-first draft to review the narrative before rendering.")
        failed=out/"storyboard_draft.json"
        if failed.exists():
            with st.expander("Draft findings that need revision"):
                st.json(json.loads(failed.read_text()).get("story_review",{}))
        return
    plan=json.loads(plan_path.read_text())
    if plan.get("timeline_identity")!=timeline["identity"]:
        st.info("The evidence changed. Generate a new story draft before approving or exporting.")
        return
    st.subheader("The story to review")
    st.write(plan["outline"]["premise"])
    st.write("**Viewer question:** "+plan["outline"]["viewer_question"])
    st.caption(f"{plan['duration_s']:.1f} seconds · {len(plan['beats'])} connected scenes · {plan.get('model','unknown')}")
    for key,label in [("initial_situation","Initial situation"),("important_change","What changes"),("resolution","Resolution")]:
        claim=plan["outline"][key]
        st.write(f"**{label}:** {claim['text']}")
        st.caption("Evidence: "+", ".join(claim["evidence_ids"]))
    for index,beat in enumerate(plan["beats"]):
        explanation=beat["explanation"]
        with st.container(border=True):
            st.subheader(f"{index+1}. {beat['role'].replace('_',' ').title()}")
            st.caption(f"Source {beat['start_s']:.1f}–{beat['end_s']:.1f}s · Output {beat['output_start_s']:.1f}–{beat['output_end_s']:.1f}s")
            st.write("**Question this scene answers:** "+explanation["question"])
            st.write("**Why it belongs:** "+explanation["purpose"])
            columns=st.columns(3)
            for column,key in zip(columns,["situation","action","consequence"]):
                with column:
                    claim=explanation[key]
                    image=next((timeline["evidence"][eid] for eid in claim["evidence_ids"] if timeline["evidence"][eid].get("type")=="source_frame"),None)
                    if image and Path(image["evidence_path"]).exists():
                        st.image(image["evidence_path"],caption=f"{key.title()} · source {image['time_s']:.1f}s")
                    st.write(f"**{key.title()}:** {claim['text']}")
                    st.caption("Evidence: "+", ".join(claim["evidence_ids"]))
            if explanation.get("connection_to_next"):
                st.write("**Connection to the next scene:** "+explanation["connection_to_next"]["text"])
                st.caption("Bridge evidence: "+", ".join(explanation["connection_to_next"]["evidence_ids"]))
            st.caption("Uncertainty: "+beat["uncertainty"])
            preview=out/"scene_previews"/(fingerprint([info,beat["start_s"],beat["end_s"]])+".mp4")
            if st.button("Preview this source scene",key="preview_"+str(index)+plan_hash(plan)):
                with st.spinner("Preparing a source excerpt with audio…"):
                    if not preview.exists():render_preview(video,beat["start_s"],beat["end_s"],preview)
            if preview.exists():st.video(str(preview))
    st.subheader("Storytelling review")
    st.write(plan["story_review"]["summary"])
    st.caption("The AI review checks sampled evidence and scene connections. Your source-scene review decides whether the story works.")
    with st.expander("Full storyboard, evidence, and review findings"):
        st.json(plan)
    review_path=out/"STORY_REVIEW.md"
    if review_path.exists():st.download_button("Download the explainable storyboard",review_path.read_bytes(),file_name="STORY_REVIEW.md")
    draft_preview=out/"match_story_draft_preview.mp4"
    if st.button("Preview full draft"):
        try:
            with st.status("Preparing the full draft with audio…",expanded=True) as status:
                metrics=render_story(video,plan,draft_preview,timeline=timeline,proposals=scenes,
                                     config=json.loads((root/"portrait_layout.json").read_text()),review_preview=True)
                (out/"draft_preview_metrics.json").write_text(json.dumps(metrics,indent=2))
                status.update(label="Draft preview ready for review",state="complete")
        except Exception as error:st.error(str(error))
    if draft_preview.exists() and draft_preview.with_suffix(".mapping.json").exists():
        mapping=json.loads(draft_preview.with_suffix(".mapping.json").read_text())
        if mapping.get("review_preview") and mapping.get("storyboard_hash")==plan_hash(plan):
            st.caption("Watch the full draft with audio before approving. The watermark identifies it as a review preview.")
            st.video(str(draft_preview))
    feedback=st.text_area("Changes you want before approval",key="feedback_"+plan_hash(plan),placeholder="For example: the middle scene doesn't show the change clearly.")
    if st.button("Save feedback for revision",disabled=not feedback.strip()):
        (out/"story_feedback.json").write_text(json.dumps({"storyboard_hash":plan_hash(plan),"feedback":feedback.strip()},indent=2))
        receipt_path=out/"story_approval.json"
        if receipt_path.exists():
            revoked=json.loads(receipt_path.read_text());revoked["revoked"]=True
            receipt_path.write_text(json.dumps(revoked,indent=2))
        state_path.write_text(json.dumps({"status":"revision_requested"}))
        st.rerun()
    confirmed=st.checkbox("I reviewed the outline, scene connections, source excerpts and draft preview, and approve this storyboard",key="confirm_"+plan_hash(plan))
    receipt_path=out/"story_approval.json"
    receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if st.button("Approve storyboard",disabled=not confirmed):
        receipt=approve_storyboard(plan)
        receipt_path.write_text(json.dumps(receipt,indent=2))
        st.success("Storyboard approved. Export is now enabled.")
    try:
        check_approval(plan,receipt);approved=True
    except ValueError:
        approved=False
    if st.button("Export approved story",type="primary",disabled=not approved):
        try:
            with st.status("Rendering your approved story…",expanded=True) as status:
                actual=render_story(video,plan,out/"match_story_v2.mp4",timeline=timeline,proposals=scenes,
                                    config=json.loads((root/"portrait_layout.json").read_text()),approval=receipt)
                (out/"story_v2_render_metrics.json").write_text(json.dumps(actual,indent=2))
                status.update(label="Approved match story is ready",state="complete")
        except Exception as error:st.error(str(error))
    output=out/"match_story_v2.mp4"
    mapping_path=output.with_suffix(".mapping.json")
    if output.exists() and mapping_path.exists():
        mapping=json.loads(mapping_path.read_text())
        if mapping.get("storyboard_hash")==plan_hash(plan):
            st.video(str(output))
            st.download_button("Download approved story",output.read_bytes(),file_name=output.name,mime="video/mp4")
    with st.expander("Compare storytelling with an encounter compilation"):
        st.write("Watch both duration-matched edits. Describe the initial situation, how it changed, and the final result; check those answers against the source.")
        if st.button("Create duration-matched compilation"):
            try:
                with st.status("Rendering the comparison compilation…") as status:
                    baseline, baseline_scenes = compilation_baseline(timeline,plan["duration_s"])
                    (out/"compilation_plan.json").write_text(json.dumps(baseline,indent=2))
                    (out/"compilation_scenes.json").write_text(json.dumps(baseline_scenes,indent=2))
                    render_story(video,baseline,out/"kill_compilation.mp4",timeline=timeline,proposals=baseline_scenes,config=json.loads((root/"portrait_layout.json").read_text()))
                    status.update(label="Comparison ready",state="complete")
            except Exception as error:
                st.error(str(error))
        comparison = out/"kill_compilation.mp4"
        if comparison.exists() and comparison.with_suffix(".mapping.json").exists():
            comparison_map = json.loads(comparison.with_suffix(".mapping.json").read_text())
            if comparison_map["source"] == info and comparison_map.get("timeline_identity") == timeline["identity"] and abs(comparison_map["shots"][-1]["output_end_s"]-plan["duration_s"]) < .05:
                st.video(str(comparison))
                st.download_button("Download comparison compilation",comparison.read_bytes(),file_name=comparison.name,mime="video/mp4")
    trace_path = out/"story_v2_agent_trace.json"
    if trace_path.exists():
        with st.expander("Story agent decisions and tool results"):
            st.json(json.loads(trace_path.read_text()))
