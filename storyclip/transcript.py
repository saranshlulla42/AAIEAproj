"""Optional local speech recognition and source-timestamped caption import."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import tempfile

from .timeline import fingerprint


def validate_transcript(segments: list[dict], duration: float, *, offset: float = 0) -> list[dict]:
    if not math.isfinite(offset) or offset < 0:
        raise ValueError("Transcript offset must be a finite nonnegative number.")
    result = []
    for segment in segments:
        a,b = float(segment["start_s"])+offset, float(segment["end_s"])+offset
        text = segment["text"].strip()
        if not math.isfinite(a) or not math.isfinite(b) or not 0 <= a < b <= duration or not text or len(text) > 500:
            raise ValueError("Invalid speech segment bounds or text.")
        result.append({"id":"speech-"+fingerprint([a,b,text])[:16], "type":"speech", "start_s":a, "end_s":b,
                       "text":text, "status":"transcribed_needs_review", "origin":segment.get("origin", "imported_transcript")})
    return sorted({s["id"]:s for s in result}.values(), key=lambda s:s["start_s"])


def import_transcript(path: Path, source: dict) -> list[dict]:
    data = json.loads(path.read_text())
    if data.get("source") != source:
        raise ValueError("Transcript belongs to a different recording.")
    return validate_transcript(data["segments"], source["duration"], offset=data.get("offset_s", 0))


def transcribe_windows(video: Path, source: dict, windows: list[tuple[float,float]], out: Path,
                       model_path: Path) -> list[dict]:
    """Use a predownloaded faster-whisper model; never download one implicitly."""
    if not model_path.is_dir():
        raise ValueError("Provide the directory of a downloaded faster-whisper model.")
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError("Install requirements-transcription.txt for optional local transcription.") from error
    identity = fingerprint({"source":source, "windows":windows, "model":str(model_path.resolve()),
                            "model_files":[[p.name,p.stat().st_size,p.stat().st_mtime_ns] for p in sorted(model_path.iterdir()) if p.is_file()]})
    cache = out / "transcripts" / f"{identity}.json"
    if cache.exists():
        return import_transcript(cache, source)
    model = WhisperModel(str(model_path), device="cpu", compute_type="int8", local_files_only=True)
    rows = []
    with tempfile.TemporaryDirectory(dir=out) as temp:
        for a,b in windows:
            if not all(math.isfinite(v) for v in [a,b]) or not 0 <= a < b <= source["duration"]:
                raise ValueError("Invalid transcription window.")
            audio = Path(temp)/"speech.wav"
            subprocess.run(["ffmpeg","-v","error","-ss",str(a),"-i",str(video),"-t",str(b-a),"-vn","-ar","16000","-ac","1","-y",str(audio)],check=True)
            segments,_ = model.transcribe(str(audio), beam_size=3, vad_filter=True, language="en")
            local = [{"start_s":max(0,s.start),"end_s":min(b-a,s.end),"text":s.text,"origin":"faster_whisper_local"} for s in segments if s.end > s.start and s.text.strip()]
            rows.extend(validate_transcript(local, source["duration"], offset=a))
    cache.parent.mkdir(parents=True,exist_ok=True)
    cache.write_text(json.dumps({"source":source,"segments":rows},indent=2))
    return import_transcript(cache,source)


def remap_captions(beats: list[dict], transcript: list[dict]) -> list[dict]:
    by_id = {t["id"]:t for t in transcript}
    captions = []
    for beat in beats:
        for tid in beat.get("transcript_ids", []):
            t = by_id[tid]
            if not beat["start_s"] <= t["start_s"] < t["end_s"] <= beat["end_s"]:
                raise ValueError("Caption is outside the selected shot.")
            captions.append({"id":tid,"start_s":beat["output_start_s"]+t["start_s"]-beat["start_s"],
                             "end_s":beat["output_start_s"]+t["end_s"]-beat["start_s"],"text":t["text"]})
    return captions


def srt_text(captions: list[dict]) -> str:
    def stamp(t):
        ms = round(t*1000)
        return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
    import textwrap
    return "\n\n".join(f"{i+1}\n{stamp(c['start_s'])} --> {stamp(c['end_s'])}\n"+"\n".join(textwrap.wrap(c["text"].replace('\n',' '),42)) for i,c in enumerate(captions))+"\n"
