"""Cached score observations and conservative, source-timestamped match context."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import subprocess

import cv2

from .candidates import flag_repeated_entries
from .detectors import crop_rect, ocr_words
from .media import frame, probe


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_score(image, config: dict, info: dict) -> list[int] | None:
    values = []
    for name in ("left", "right"):
        x, y, w, h = crop_rect(config[name], info, config)
        crop = image[y:y+h, x:x+w]
        words = ocr_words(crop, digits=True)
        text = "".join(w["text"] for w in words)
        values.append(int(text) if text.isdigit() and int(text) <= 40
                      and all(w["score"] >= 50 for w in words) else None)
    return values if all(v is not None for v in values) else None


def score_pass(video: Path, config: dict, out: Path, *, start: float = 0,
               end: float | None = None, step: float = 30) -> list[dict]:
    info = probe(video)
    end = info["duration"] if end is None else end
    if not all(math.isfinite(v) for v in [start, end, step]) or not 0 <= start < end <= info["duration"] or not 1 <= step <= 120:
        raise ValueError("Invalid score scan interval or sampling step.")
    identity = fingerprint({"source": info, "config": config, "version": Path(__file__).read_text()})[:16]
    cache = out / "scores" / identity
    cache.mkdir(parents=True, exist_ok=True)
    times = [round(start+i*step, 3) for i in range(math.ceil((end-start)/step))]
    times += [round(max(start, end-0.2), 3)]

    def sample(t):
        key = f"{t:010.3f}"
        record = cache / f"{key}.json"
        if record.exists():
            saved = json.loads(record.read_text())
            if Path(saved["evidence_path"]).exists():
                return saved
        image_path = cache / f"{key}.jpg"
        frame(video, t, image_path)
        score = read_score(cv2.imread(str(image_path)), config, info)
        result = {"id": f"score-{round(t*1000):09d}", "type": "score", "time_s": t,
                  "score": score, "status": "unconfirmed_ocr" if score else "unknown",
                  "team_side": None, "mapping_verified": False,
                  "evidence_path": str(image_path.resolve()), "uncertainty": "Sampled OCR; not exact round timing."}
        record.write_text(json.dumps(result, indent=2))
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        observations = list(pool.map(sample, sorted(set(times))))
    # Refine changing/unknown adjacent samples once; no recursive unbounded scan.
    if step > 5:
        extra = [(a["time_s"]+b["time_s"])/2 for a, b in zip(observations, observations[1:])
                 if a["score"] != b["score"] or a["score"] is None]
        with ThreadPoolExecutor(max_workers=3) as pool:
            observations += list(pool.map(sample, extra))
    return sorted(observations, key=lambda o: o["time_s"])


def validate_anchors(data: dict, source: dict) -> list[dict]:
    if data.get("source") != source:
        raise ValueError("Anchor file belongs to a different or changed recording.")
    anchors = []
    for record in data.get("observations", []):
        a = dict(record)
        t = a.get("time_s")
        score = a.get("score")
        if not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t < source["duration"]:
            raise ValueError("Anchor timestamp is outside the recording.")
        if score is not None and (not isinstance(score, list) or len(score) != 2 or
                                  any(type(v) is not int or not 0 <= v <= 40 for v in score)):
            raise ValueError("Anchor score must be two nonnegative integer scores.")
        if a.get("team_side") not in (None, "left", "right"):
            raise ValueError("Invalid team mapping.")
        if not a.get("review_note") or not a.get("evidence_path") or not Path(a["evidence_path"]).is_file():
            raise ValueError("Reviewed anchors need a source image and review note.")
        if a.get("outcome") not in (None, "victory", "defeat", "draw"):
            raise ValueError("Invalid reviewed outcome.")
        if a.get("outcome"):
            if not a.get("team_side") or score is None:
                raise ValueError("An outcome needs a score and verified team mapping.")
            own,other = score if a["team_side"] == "left" else score[::-1]
            if (a["outcome"] == "victory" and own <= other) or (a["outcome"] == "defeat" and own >= other) or (a["outcome"] == "draw" and own != other):
                raise ValueError("Reviewed outcome contradicts the mapped score.")
        a.update(id=f"anchor-{round(t*1000):09d}", type="score", status="reviewed_anchor",
                 mapping_verified=bool(a.get("team_side")), uncertainty="Assisted visual review; mapping applies at this observation only.")
        anchors.append(a)
    if len({a["id"] for a in anchors}) != len(anchors):
        raise ValueError("Duplicate anchor timestamp.")
    return anchors


def reconcile(observations: list[dict]) -> list[dict]:
    """Reject isolated readings and impossible regressions without guessing missing scores."""
    rows = [dict(o) for o in sorted(observations, key=lambda o: o["time_s"])]
    previous = None
    for i, row in enumerate(rows):
        if row["status"] == "reviewed_anchor":
            previous = row
            continue
        score = row.get("score")
        if score is None:
            continue
        neighbors = rows[max(0, i-1):i] + rows[i+1:i+2]
        repeated = any(n.get("score") == score and abs(n["time_s"]-row["time_s"]) <= 65 for n in neighbors)
        plausible = previous is None or (all(a >= b for a, b in zip(score, previous["score"]))
                                        and sum(score)-sum(previous["score"]) <= max(1, math.ceil((row["time_s"]-previous["time_s"])/20)))
        row["status"] = "consistent_ocr" if repeated and plausible else "needs_review"
        if row["status"] == "consistent_ocr":
            previous = row
    return rows


def build_timeline(source: dict, scan: dict, observations: list[dict], *, transcript: list[dict] | None = None) -> dict:
    if scan["manifest"]["source"] != source:
        raise ValueError("Event scan belongs to a different recording.")
    if scan["manifest"]["start"] != 0 or scan["manifest"]["end"] < source["duration"]-0.1:
        raise ValueError("Match Story requires full-recording event discovery; run a full scan first.")
    observations = reconcile(observations)
    events = flag_repeated_entries(scan["events"])
    evidence = {o["id"]: o for o in observations}
    evidence.update({e["id"]: e for e in events})
    transcript = transcript or []
    evidence.update({t["id"]: t for t in transcript})
    # Every interval is present, including quiet stretches and unknown readings.
    boundaries = sorted(set([0., source["duration"]]+[o["time_s"] for o in observations]))
    rounds = []
    by_time = {}
    for o in observations:
        if o["time_s"] not in by_time or o["status"] == "reviewed_anchor":
            by_time[o["time_s"]] = o
    for index, (a, b) in enumerate(zip(boundaries, boundaries[1:])):
        before, after = by_time.get(a), by_time.get(b)
        trusted = lambda o: o and o["status"] in ("consistent_ocr", "reviewed_anchor") and o.get("score") is not None
        same = trusted(before) and trusted(after) and before["score"] == after["score"]
        transition = trusted(before) and trusted(after) and sum(after["score"])-sum(before["score"]) == 1 and all(x >= y for x, y in zip(after["score"], before["score"]))
        hp = [h for h in scan["health"] if a <= h["time_s"] < b and h["displayed_hp"] is not None]
        rounds.append({"id": f"interval-{index+1:04d}", "start_s": a, "end_s": b,
                       "kind": "stable_score_interval" if same else "round_boundary_bracket" if transition else "unresolved_interval",
                       "score_before": before["score"] if trusted(before) else None,
                       "score_after": after["score"] if trusted(after) else None,
                       "evidence_ids": [o["id"] for o in [before, after] if o],
                       "team_side": before.get("team_side") if trusted(before) else None,
                       "event_ids": [e["id"] for e in events if a <= e["time_s"] < b],
                       "health_min": min((h["displayed_hp"] for h in hp), default=None),
                       "health_observation": min(hp, key=lambda h:h["displayed_hp"]) if hp else None,
                       "transcript_ids": [t["id"] for t in transcript if t["start_s"] < b and t["end_s"] > a],
                       "deaths": [], "uncertainty": "Bounds are sample times, not exact round start/end. Death attribution is unavailable."})
    data = {"version": 1, "source": source, "observations": observations, "intervals": rounds,
            "events": events, "transcript": transcript, "evidence": evidence,
            "assisted": any(o["status"] == "reviewed_anchor" for o in observations),
            "outcome_ids": [o["id"] for o in observations if o.get("outcome") and o.get("mapping_verified")],
            "limitations": ["OCR is fallible; unknown intervals are retained.", "Deaths are not calibrated and are not inferred from health.",
                            "Team mapping is local to reviewed anchors, including after side changes."]}
    data["identity"] = fingerprint(data)
    return data


def prepare_timeline(video: Path, scan: dict, config: dict, out: Path, *, anchors: Path | None = None,
                     transcript: list[dict] | None = None) -> dict:
    source = probe(video)
    reviewed = validate_anchors(json.loads(anchors.read_text()), source) if anchors else []
    observations = score_pass(video, config, out, step=config.get("step_s", 30))
    timeline = build_timeline(source, scan, observations+reviewed, transcript=transcript)
    out.mkdir(parents=True, exist_ok=True)
    (out / "timeline.json").write_text(json.dumps(timeline, indent=2))
    return timeline
