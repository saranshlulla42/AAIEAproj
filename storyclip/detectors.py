from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import cv2
import numpy as np

from .media import probe


def ocr_words(image: np.ndarray, *, digits: bool = False) -> list[dict]:
    """Run the installed OCR executable; retain boxes and its uncalibrated scores."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    if digits:
        # White HUD glyphs on a changing background. Use their brightness as a mask.
        gray = 255 - cv2.threshold(gray, 175, 255, cv2.THRESH_BINARY)[1]
    ok, encoded = cv2.imencode(".png", gray)
    if not ok:
        return []
    cmd = ["tesseract", "stdin", "stdout", "--psm", "7"]
    if digits:
        cmd += ["-c", "tessedit_char_whitelist=0123456789"]
    else:
        cmd += ["-c", "load_system_dawg=0", "-c", "load_freq_dawg=0"]
    cmd += ["tsv"]
    result = subprocess.run(cmd, input=encoded.tobytes(), capture_output=True, check=True, timeout=10)
    words = []
    for row in csv.DictReader(io.StringIO(result.stdout.decode()), delimiter="\t"):
        if row["text"].strip():
            words.append({"text": row["text"].strip(), "score": float(row["conf"]),
                          "x": int(row["left"]) / 3, "width": int(row["width"]) / 3})
    return words


def feed_rows(feed: np.ndarray) -> list[tuple[int, int]]:
    hsv = cv2.cvtColor(feed, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    colored = (s > 65) & (v > 100) & (((h > 60) & (h < 100)) | (h < 12) | (h > 170))
    active = colored.mean(axis=1) > 0.14
    # Each colored entry occupies a horizontal band, with a gap between entries.
    padded = np.pad(active.astype(np.int8), (1, 1))
    begins = np.where(np.diff(padded) == 1)[0]
    ends = np.where(np.diff(padded) == -1)[0]
    return [(max(0, int(a) - 2), min(feed.shape[0], int(b) + 2))
            for a, b in zip(begins, ends) if 12 <= b - a <= 48]


def clean(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def read_player_kill(row: np.ndarray, config: dict) -> dict | None:
    words = ocr_words(row)
    player = clean(config["player_name"])
    own = [w for w in words if clean(w["text"]) == player and w["x"] < config["killer_max_x"]
           and w["score"] >= 35]
    if not own:
        return None
    names = {clean(n): n for n in config["known_names"] if clean(n) != player}
    victims = [w for w in words if w["x"] > config["killer_max_x"] and clean(w["text"]) in names]
    if not victims or victims[-1]["score"] < 25:
        return None  # An attributed player name alone is insufficient evidence.
    victim = victims[-1]
    return {"killer": config["player_name"], "victim": names[clean(victim["text"])],
            "ocr_score": min(own[0]["score"], victim["score"]),
            "ocr_text": " ".join(w["text"] for w in words)}


def crop_rect(rect: list[int], info: dict, config: dict) -> list[int]:
    sx, sy = info["width"] / config["reference_width"], info["height"] / config["reference_height"]
    return [round(rect[0] * sx), round(rect[1] * sy), round(rect[2] * sx), round(rect[3] * sy)]


def scan(video: Path, config: dict, out: Path, *, start: float = 0, end: float | None = None,
         fps: float | None = None) -> dict:
    if not shutil.which("tesseract"):
        raise RuntimeError("Tesseract is missing. Install tesseract-ocr first.")
    info = probe(video)
    end = info["duration"] if end is None else min(end, info["duration"])
    if not 0 <= start < end:
        raise ValueError("Invalid scan interval.")
    fps = fps or config["sample_fps"]
    if not 0.5 <= fps <= 8:
        raise ValueError("Sampling rate must be between 0.5 and 8 fps.")
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"source": info, "config": config, "start": start, "end": end, "fps": fps,
                "detector_version": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    cache = out / "scan.json"
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved["manifest"] == manifest:
            print("Using cached event scan.", flush=True)
            return saved
    fx, fy, fw, fh = crop_rect(config["killfeed"], info, config)
    hx, hy, hw, hh = crop_rect(config["health"], info, config)
    # Keep the small crops at the calibration resolution for the detector.
    cw, ch = config["killfeed"][2:]
    hpw, hph = config["health"][2:]
    filter_graph = (
        f"fps={fps},split=2[f][h];[f]crop={fw}:{fh}:{fx}:{fy},scale={cw}:{ch}[fc];"
        f"[h]crop={hw}:{hh}:{hx}:{hy},scale={hpw}:{hph},pad={cw}:{hph}:0:0[hc];"
        "[fc][hc]vstack=inputs=2[out]"
    )
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(video), "-t", str(end-start),
           "-filter_complex", filter_graph, "-map", "[out]", "-an", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    events, health = [], []
    last_seen: dict[str, dict] = {}
    row_cache: list[tuple[np.ndarray, dict | None]] = []
    recent_hp: list[tuple[float, int]] = []
    hp_cache = None
    hp_value = None
    started = time.monotonic()
    frame_bytes = cw * (ch + hph) * 3
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors)
        try:
            index = 0
            while True:
                data = bytearray()
                while len(data) < frame_bytes:
                    block = process.stdout.read(frame_bytes - len(data))
                    if not block:
                        break
                    data.extend(block)
                if not data:
                    break
                if len(data) != frame_bytes:
                    raise RuntimeError("Incomplete frame from FFmpeg.")
                image = np.frombuffer(data, np.uint8).reshape(ch+hph, cw, 3)
                timestamp = round(start + index / fps, 3)
                feed, hp = image[:ch], image[ch:, :hpw]
                # OCR health twice per source second at most; unobserved or invalid HP is unknown.
                if index % max(1, round(fps / 2)) == 0:
                    hp_mask = cv2.threshold(cv2.cvtColor(hp, cv2.COLOR_BGR2GRAY), 175, 255, cv2.THRESH_BINARY)[1]
                    if hp_cache is None or np.abs(hp_mask.astype(float)-hp_cache.astype(float)).mean() > 1.5:
                        hpwords = ocr_words(hp, digits=True)
                        hptxt = "".join(w["text"] for w in hpwords)
                        hp_value = int(hptxt) if hptxt.isdigit() and 1 <= int(hptxt) <= 150 else None
                        hp_cache = hp_mask.copy()
                    value = hp_value
                    recent_hp.append((timestamp, value))
                    recent_hp = [(t, v) for t, v in recent_hp if timestamp-t <= 1.1]
                    repeated = value is not None and sum(v == value for t, v in recent_hp) >= 2
                    observed = value if repeated else None
                    health.append({"time_s": timestamp, "displayed_hp": observed,
                                   "raw_hp": value, "status": "consistent" if repeated else "unknown"})
                next_cache = []
                for a, b in feed_rows(feed):
                    row = feed[a:b].copy()
                    # Cache near-identical persistent entries; OCR only when their pixels change.
                    small = cv2.resize(row, (240, 20))
                    existing = next((d for img, d in row_cache
                                     if np.abs(small.astype(float)-img.astype(float)).mean() < 7), "missing")
                    parsed = read_player_kill(row, config) if existing == "missing" else existing
                    next_cache.append((small, parsed))
                    if parsed is None:
                        continue
                    key = f"{parsed['killer']}|{parsed['victim']}"
                    previous = last_seen.get(key)
                    if previous and timestamp - previous["last_seen_s"] <= 2.0:
                        previous["last_seen_s"] = timestamp
                        previous["observations"] += 1
                        continue
                    event_id = f"kill-{len(events)+1:04d}"
                    evidence = out / "evidence" / f"{event_id}.png"
                    evidence.parent.mkdir(exist_ok=True)
                    cv2.imwrite(str(evidence), row)
                    preceding = next(((h["time_s"], h["displayed_hp"]) for h in reversed(health)
                                      if h["time_s"] < timestamp and h["displayed_hp"] is not None
                                      and timestamp-h["time_s"] <= 1.0), None)
                    hp_at_kill = preceding[1] if preceding else None
                    event = {"id": event_id, "time_s": timestamp, "last_seen_s": timestamp,
                             "type": "player_kill", **parsed, "observations": 1,
                             "displayed_hp_before": hp_at_kill,
                             "health_time_s": preceding[0] if preceding else None,
                             "low_health": hp_at_kill is not None and hp_at_kill <= config["low_health"],
                             "evidence_path": str(evidence.resolve()), "status": "needs_review"}
                    events.append(event)
                    last_seen[key] = event
                row_cache = next_cache
                index += 1
                if index % max(1, int(fps*30)) == 0:
                    print(f"Scanned {timestamp:.0f}s / {end:.0f}s; {len(events)} attributed events", flush=True)
            if process.wait() != 0:
                errors.seek(0)
                raise RuntimeError(errors.read().decode()[-3000:])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    for event in events:
        event["status"] = "consistent_ocr" if event["observations"] >= 2 else "needs_review"
    result = {"manifest": manifest, "events": events, "health": health,
              "metrics": {"sampled_frames": index, "elapsed_s": round(time.monotonic()-started, 2),
                          "event_count": len(events), "health_known": sum(h["displayed_hp"] is not None for h in health)}}
    cache.write_text(json.dumps(result, indent=2))
    (out / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events)+"\n")
    (out / "health.jsonl").write_text("\n".join(json.dumps(h) for h in health)+"\n")
    return result
