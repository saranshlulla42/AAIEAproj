from __future__ import annotations


def flag_repeated_entries(events: list[dict]) -> list[dict]:
    """A close repeated killer/victim pair may be a persistent feed entry.

    Flag it for review instead of allowing an OCR interruption to inflate a
    multi-kill score. Legitimate repeated eliminations after revival also need
    review; this is a conservative ambiguity rule, not a claim of ground truth.
    """
    result = []
    previous = {}
    for original in sorted(events, key=lambda e: e["time_s"]):
        event = dict(original)
        pair = (event.get("killer"), event["victim"])
        earlier = previous.get(pair)
        if earlier and event["time_s"] - earlier.get("last_seen_s", earlier["time_s"]) <= 8:
            event["status"] = "repeat_needs_review"
            event["possible_duplicate_of"] = earlier["id"]
        else:
            previous[pair] = event
        result.append(event)
    return result


def propose(events: list[dict], source_duration: float, *, limit: int = 8) -> list[dict]:
    """Score event clusters transparently, then suppress overlapping proposals."""
    accepted = sorted((e for e in events if e["status"] == "consistent_ocr"), key=lambda e: e["time_s"])
    proposals = []
    for anchor in accepted:
        cluster = [e for e in accepted if anchor["time_s"] <= e["time_s"] <= anchor["time_s"]+15]
        start = max(0, anchor["time_s"]-12)
        end = min(source_duration, max(start+45, cluster[-1]["time_s"]+10))
        if end-start < 30:
            start = max(0, end-45)
        contained = [e for e in accepted if start <= e["time_s"] <= end]
        low = sum(e["low_health"] for e in cluster)
        score = 3*len(cluster) + 2*low
        proposals.append({"start_s": round(start, 3), "end_s": round(end, 3),
                          "score": score, "cluster_kills": len(cluster), "low_health_kills": low,
                          "event_ids": [e["id"] for e in contained],
                          "events": [{k: e[k] for k in ["id", "time_s", "victim", "displayed_hp_before", "low_health", "status"]} for e in contained],
                          "notes": "HUD-derived candidate; narrative and gameplay need review."})
    selected = []
    for candidate in sorted(proposals, key=lambda c: c["score"], reverse=True):
        overlaps = any(max(0, min(c["end_s"], candidate["end_s"])-max(c["start_s"], candidate["start_s"]))
                       / min(c["end_s"]-c["start_s"], candidate["end_s"]-candidate["start_s"]) > 0.5
                       for c in selected)
        if not overlaps:
            candidate["id"] = f"candidate-{len(selected)+1:02d}"
            selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected
