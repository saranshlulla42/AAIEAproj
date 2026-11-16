"""Explainable story planning and approval, separate from technical clip checks."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import json

from pydantic import BaseModel, ConfigDict, Field
from .timeline import fingerprint


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Claim(StrictModel):
    text: str = Field(min_length=8,max_length=400)
    evidence_ids: list[str] = Field(min_length=1,max_length=12)


class Intent(StrictModel):
    scene_id: str
    role: Literal["setup","development","setback","turning_point","action","outcome"]
    question: str = Field(min_length=10,max_length=250)
    purpose: str = Field(min_length=15,max_length=400)


class StoryOutline(StrictModel):
    premise: str = Field(min_length=40,max_length=1200)
    viewer_question: str = Field(min_length=10,max_length=250)
    initial_situation: Claim
    important_change: Claim
    resolution: Claim
    intents: list[Intent] = Field(min_length=3,max_length=5)


class SceneReview(StrictModel):
    scene_id: str
    start_s: float
    end_s: float
    situation: Claim
    action: Claim
    consequence: Claim
    useful_for_story: bool
    completeness: Literal["sufficient","insufficient"]
    uncertainty: str = Field(min_length=5,max_length=500)


class BeatExplanation(StrictModel):
    question: str = Field(min_length=10,max_length=250)
    purpose: str = Field(min_length=15,max_length=400)
    situation: Claim
    action: Claim
    consequence: Claim
    connection_to_next: Claim | None = None


class StoryFinding(StrictModel):
    scene_id: str | None = None
    issue: str
    remedy: str


class StoryCritique(StrictModel):
    verdict: Literal["pass","revise"]
    initial_situation_clear: bool
    change_clear: bool
    outcome_clear: bool
    scenes_connected: bool
    claims_supported: bool
    cuts_complete: bool
    findings: list[StoryFinding]
    summary: str = Field(min_length=20,max_length=1000)


def validate_claim(claim: Claim, timeline: dict, *, start: float | None = None, end: float | None = None) -> list[dict]:
    records = []
    for eid in claim.evidence_ids:
        e = timeline["evidence"].get(eid)
        if e is None:
            raise ValueError(f"Unknown explanation evidence {eid}.")
        if e.get("type") == "speech":
            a,b=e["start_s"],e["end_s"]
        else:
            a=e.get("time_s");b=a
        if a is None:
            raise ValueError(f"Explanation evidence {eid} has no source timestamp.")
        if (start is not None and a < start) or (end is not None and (a >= end or b > end)):
            raise ValueError(f"Explanation evidence {eid} at {a}–{b}s is outside cut [{start}, {end})s. "
                             "Start at or before the first cited timestamp; end strictly after every cited point timestamp.")
        if e.get("type") == "score" and e.get("status") not in {"consistent_ocr","reviewed_anchor"}:
            raise ValueError("An uncertain score cannot support an explanation.")
        if e.get("type") == "player_kill" and e.get("status") != "consistent_ocr":
            raise ValueError("Tentative or repeated events cannot support a factual explanation.")
        records.append(e)
    return records


def validate_outline(raw: dict, timeline: dict, proposals: list[dict]) -> StoryOutline:
    outline=StoryOutline.model_validate(raw)
    scenes={p["id"]:p for p in proposals}
    ids=[i.scene_id for i in outline.intents]
    if len(ids) != len(set(ids)) or any(i not in scenes for i in ids):
        raise ValueError("Outline needs 3-5 distinct known scenes.")
    if outline.intents[0].role != "setup" or outline.intents[-1].role != "outcome":
        raise ValueError("Outline must start with setup and end with resolution.")
    if ids != sorted(ids,key=lambda i:scenes[i]["start_s"]):
        raise ValueError("Outline scenes must be chronological.")
    duration=timeline["source"]["duration"]
    selected=[scenes[i] for i in ids]
    if selected[0]["start_s"] >= duration/3 or selected[-1]["end_s"] <= 2*duration/3 or not any(duration/3 <= (p["start_s"]+p["end_s"])/2 <= 2*duration/3 for p in selected):
        raise ValueError("A full-match outline needs an early setup, middle development and late resolution. A late-only finish is not a match story.")
    records=[validate_claim(c,timeline) for c in [outline.initial_situation,outline.important_change,outline.resolution]]
    # A change legitimately cites both the before and after state. Its temporal
    # endpoint is the latest observation, not the earliest supporting citation.
    # The decisive change and final result can share a sampled frame.
    times=[max(e.get("time_s",e.get("end_s",e.get("start_s"))) for e in rows) for rows in records]
    if not times[0] < times[1] <= times[2]:
        raise ValueError("Initial situation, change and resolution need chronological evidence.")
    if timeline["outcome_ids"] and not set(outline.resolution.evidence_ids) & set(timeline["outcome_ids"]):
        raise ValueError("Outline resolution must cite the observed final result.")
    coverage={};missing=[];alternatives={}
    for claim in [outline.initial_situation,outline.important_change,outline.resolution]:
        for e in validate_claim(claim,timeline):
            timestamp=e.get("time_s",e.get("start_s"))
            available=[p["id"] for p in proposals if p.get("context_start_s",p["start_s"])<=timestamp<p.get("context_end_s",p["end_s"])]
            coverage[e["id"]]=available
            if not any(p.get("context_start_s",p["start_s"]) <= timestamp < p.get("context_end_s",p["end_s"]) for p in [scenes[i] for i in ids]):
                missing.append(f"Outline evidence {e['id']} at {timestamp}s is outside all selected scenes {ids}. Available scenes: {available}.")
                if e.get("type")=="score":
                    matches=[o for o in timeline["observations"] if o.get("score")==e.get("score") and o.get("status") in {"reviewed_anchor","consistent_ocr"}
                             and any(p.get("context_start_s",p["start_s"])<=o["time_s"]<p.get("context_end_s",p["end_s"]) for p in selected)]
                    matches.sort(key=lambda o:(o.get("status")!="reviewed_anchor",min(abs(o["time_s"]-(p["start_s"]+p["end_s"])/2) for p in selected)))
                    alternatives[e["id"]]=[{"id":o["id"],"time_s":o["time_s"],"score":o["score"],"mapping_verified":o.get("mapping_verified",False)} for o in matches[:3]]
    if missing:
        raise ValueError(" ".join(missing)+f" Required coverage for ALL core citations: {coverage}. "
                         "Cover every group simultaneously within 3-5 intents plus early/middle/late coverage. "
                         "Replace redundant opening/action scenes rather than removing another required scene, or narrow the claims and their citations. "
                         f"Equivalent score observations INSIDE the selected scenes: {alternatives}. "
                         "For a score-state claim, rewrite its timestamp/wording and citation to an equivalent in-scene observation if appropriate. Never change source timestamps or keep an unsupported team attribution.")
    return outline


def validate_scene_review(raw: dict, timeline: dict, inspection: dict) -> SceneReview:
    review=SceneReview.model_validate(raw)
    if review.scene_id != inspection["scene_id"] or not inspection["start_s"] <= review.start_s < review.end_s <= inspection["end_s"]:
        raise ValueError("Scene review must stay within the inspected context window.")
    if not review.useful_for_story or review.completeness != "sufficient":
        return review
    frame_ids={e["id"] for e in inspection["frames"]}
    for claim in [review.situation,review.action,review.consequence]:
        validate_claim(claim,timeline,start=review.start_s,end=review.end_s)
        if not frame_ids & set(claim.evidence_ids):
            raise ValueError("Each scene explanation must cite an inspected source frame.")
    situation_times=[timeline["evidence"][i].get("time_s",timeline["evidence"][i].get("start_s")) for i in review.situation.evidence_ids]
    action_times=[timeline["evidence"][i].get("time_s",timeline["evidence"][i].get("start_s")) for i in review.action.evidence_ids]
    consequence_times=[timeline["evidence"][i].get("time_s",timeline["evidence"][i].get("start_s")) for i in review.consequence.evidence_ids]
    if max(action_times) < min(situation_times):
        raise ValueError("A scene situation must precede its action.")
    if max(consequence_times) < min(action_times):
        raise ValueError("A scene consequence cannot precede its action.")
    return review


def narrative_checks(plan: dict, timeline: dict, proposals: list[dict], reviews: dict[str,dict]) -> dict:
    outline=validate_outline(plan.get("outline") or {},timeline,proposals)
    beats=plan["beats"]
    if [b["scene_id"] for b in beats] != [i.scene_id for i in outline.intents]:
        raise ValueError("Storyboard must implement its outline, not switch to unrelated scenes.")
    all_cited=set()
    for index,beat in enumerate(beats):
        explanation=BeatExplanation.model_validate(beat.get("explanation") or {})
        review=SceneReview.model_validate(reviews.get(beat["scene_id"]) or {})
        if not review.useful_for_story or review.completeness != "sufficient":
            raise ValueError("Every selected scene needs a useful, complete visual review.")
        if not review.start_s <= beat["start_s"] < beat["end_s"] <= review.end_s:
            raise ValueError("Cuts must stay inside the reviewed complete scene.")
        intent=outline.intents[index]
        if beat["role"] != intent.role or explanation.question != intent.question or explanation.purpose != intent.purpose:
            raise ValueError("Each beat must answer the question and purpose agreed in the outline.")
        for key in ["situation","action","consequence"]:
            claim=getattr(explanation,key)
            validate_claim(claim,timeline,start=beat["start_s"],end=beat["end_s"])
            reviewed=getattr(review,key)
            if claim != reviewed:
                raise ValueError("Storyboard explanations must preserve the inspected scene's reviewed facts.")
            if not set(claim.evidence_ids) <= set(beat["evidence_ids"]):
                raise ValueError("Explainable facts must be included in the beat's evidence citations.")
            all_cited.update(claim.evidence_ids)
        if index < len(beats)-1:
            bridge=explanation.connection_to_next
            if bridge is None:
                raise ValueError("Each non-final beat needs an evidence-backed connection to the next.")
            if len(bridge.text)>130:
                raise ValueError("Visible bridges must be short (at most 130 characters).")
            validate_claim(bridge,timeline)
            if not set(bridge.evidence_ids) & set(beat["evidence_ids"]) or not set(bridge.evidence_ids) & set(beats[index+1]["evidence_ids"]):
                raise ValueError(f"Bridge {index+1} ({beat['scene_id']} → {beats[index+1]['scene_id']}) must cite both adjacent cuts. "
                                 f"Available from evidence: {beat['evidence_ids']}; available to evidence: {beats[index+1]['evidence_ids']}. "
                                 "Choose at least one supported citation from each selected cut, using adjacent_pairs.")
            if not set(bridge.evidence_ids) <= set(beat["evidence_ids"]) | set(beats[index+1]["evidence_ids"]):
                raise ValueError("A bridge must connect evidence in the two adjacent scenes.")
        elif explanation.connection_to_next is not None:
            raise ValueError("The final beat resolves the story; it has no next-scene bridge.")
    needed=set(outline.initial_situation.evidence_ids+outline.important_change.evidence_ids+outline.resolution.evidence_ids)
    if not needed <= set(i for b in beats for i in b["evidence_ids"]):
        raise ValueError("Selected footage must show every core fact of the outline.")
    return {"outline":outline.model_dump(),"scene_reviews":reviews,"planning_version":2}


def critique_passed(review: dict) -> bool:
    critique=StoryCritique.model_validate(review)
    return critique.verdict == "pass" and not critique.findings and all(getattr(critique,key) for key in
        ["initial_situation_clear","change_clear","outcome_clear","scenes_connected","claims_supported","cuts_complete"])


def plan_hash(plan: dict) -> str:
    return fingerprint(plan)


def approve_storyboard(plan: dict) -> dict:
    if plan.get("planning_version") != 2 or not critique_passed(plan.get("story_review") or {}):
        raise ValueError("Replan and pass storytelling review before approving a story.")
    return {"storyboard_hash":plan_hash(plan),"timeline_identity":plan["timeline_identity"],
            "approved_at":datetime.now(timezone.utc).isoformat(),"approved_by":"human_review"}


def check_approval(plan: dict, receipt: dict | None) -> None:
    if plan.get("planning_version") != 2 or not critique_passed(plan.get("story_review") or {}):
        raise ValueError("This is an old or unreviewed storyboard. Generate a story-first draft before exporting.")
    if not receipt or receipt.get("revoked") or receipt.get("storyboard_hash") != plan_hash(plan) or receipt.get("timeline_identity") != plan["timeline_identity"]:
        raise ValueError("Review and approve this exact storyboard before rendering. Changes invalidate approval.")


def review_markdown(plan: dict) -> str:
    lines=["# Story draft for review", "", plan["outline"]["premise"], "", f"Viewer question: {plan['outline']['viewer_question']}", ""]
    for index,b in enumerate(plan["beats"]):
        e=b["explanation"]
        lines += [f"## {index+1}. {b['role']} — source {b['start_s']:.1f}–{b['end_s']:.1f}s", "",
                  f"Question: {e['question']}",f"Purpose: {e['purpose']}", ""]
        for key in ["situation","action","consequence","connection_to_next"]:
            if e.get(key):
                lines += [f"{key.replace('_',' ').title()}: {e[key]['text']}",f"Evidence: {', '.join(e[key]['evidence_ids'])}", ""]
        lines += [f"Uncertainty: {b['uncertainty']}", ""]
    lines += ["## Storytelling review", "",plan["story_review"]["summary"],"", "Awaiting human review. No full video is rendered automatically."]
    return "\n".join(lines)+"\n"
