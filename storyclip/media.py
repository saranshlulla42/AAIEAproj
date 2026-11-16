from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


def probe(video: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    return {
        "video": str(video.resolve()), "duration": float(data["format"]["duration"]),
        "width": stream["width"], "height": stream["height"],
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
        "source_size": video.stat().st_size, "source_mtime_ns": video.stat().st_mtime_ns,
    }


def frame(video: Path, timestamp: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(video),
        "-frames:v", "1", "-update", "1", "-y", str(output),
    ], check=True)


def render(video: Path, start: float, end: float, output: Path, *, config: dict | None = None) -> dict:
    info = probe(video)
    if not (0 <= start < end <= info["duration"]):
        raise ValueError("Clip boundaries must be within the source video.")
    if not 30 <= end - start <= 60:
        raise ValueError("Clip duration must be between 30 and 60 seconds.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if config and config.get("facecam"):
        x, y, w, h = config["facecam"]
        sx = info["width"] / config["reference_width"]
        sy = info["height"] / config["reference_height"]
        x, y, w, h = round(x*sx), round(y*sy), round(w*sx), round(h*sy)
        graph = (
            "color=c=0x121826:s=720x1280:r=30[bg];[0:v]split[g][c];"
            "[g]scale=720:405,setsar=1,fps=30[game];"
            f"[c]crop={w}:{h}:{x}:{y},scale=720:350,setsar=1,fps=30[cam];"
            "[bg][cam]overlay=0:155:shortest=1[bc];"
            "[bc][game]overlay=0:600:shortest=1,"
            "drawtext=text='VALORANT':fontcolor=white:fontsize=44:x=36:y=55,"
            "drawtext=text='RANKED GAMEPLAY':fontcolor=0x9babc6:fontsize=22:x=36:y=1100[out]"
        )
        filters = ["-filter_complex", graph, "-map", "[out]"]
    else:
        filters = ["-map", "0:v:0", "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=0x121826,setsar=1,fps=30"]
    with tempfile.TemporaryDirectory(prefix=".render-", dir=output.parent) as temp:
        temporary = Path(temp) / "clip.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-ss", str(start), "-i", str(video),
            "-t", str(end - start), *filters, "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-y", str(temporary),
        ], check=True)
        actual = probe(temporary)
        if (actual["width"], actual["height"]) != (720, 1280):
            raise RuntimeError("Rendered dimensions are incorrect.")
        if abs(actual["duration"] - (end - start)) > 0.25:
            raise RuntimeError("Rendered duration differs from the edit plan.")
        if info["has_audio"] and not actual["has_audio"]:
            raise RuntimeError("Source audio was lost during rendering.")
        temporary.replace(output)
    return probe(output)


def _portrait_filters(info: dict, config: dict | None) -> tuple[list[str], str]:
    if config and config.get("facecam"):
        x,y,w,h = config["facecam"]
        sx,sy = info["width"]/config["reference_width"],info["height"]/config["reference_height"]
        x,y,w,h = round(x*sx),round(y*sy),round(w*sx),round(h*sy)
        if not 0 <= x < x+w <= info["width"] or not 0 <= y < y+h <= info["height"]:
            raise ValueError("Facecam crop is outside the source.")
        graph = ("color=c=0x121826:s=720x1280:r=30[bg];[0:v]split[g][c];"
                 "[g]scale=720:405,setsar=1,fps=30[game];"
                 f"[c]crop={w}:{h}:{x}:{y},scale=720:350,setsar=1,fps=30[cam];"
                 "[bg][cam]overlay=0:155:shortest=1[bc];"
                 "[bc][game]overlay=0:600:shortest=1")
        return ["-filter_complex"], graph
    return ["-vf"], "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=0x121826,setsar=1,fps=30"


def render_story(video: Path, plan: dict, output: Path, *, timeline: dict, proposals: list[dict], config: dict | None = None, approval: dict | None = None, review_preview: bool = False) -> dict:
    """Render an approved export or a visibly marked draft for human review."""
    from .story import Beat, validate_storyboard
    from .narrative import plan_hash
    from .transcript import remap_captions, srt_text
    import textwrap
    if review_preview and "draft" not in output.stem.lower():
        raise ValueError("A review preview must use a distinct draft filename.")
    info = probe(video)
    if info != plan.get("source") or info != timeline["source"] or plan.get("timeline_identity") != timeline["identity"]:
        raise ValueError("Storyboard/source/timeline identity mismatch. Plan again for this recording.")
    if plan.get("planning_version") == 2 or plan.get("mode") in {"pi_match_story", "assisted_match_story"}:
        from .narrative import check_approval, narrative_checks, critique_passed
        if review_preview:
            if plan.get("planning_version")!=2 or not critique_passed(plan.get("story_review") or {}):
                raise ValueError("A draft preview requires a story-first plan that passes AI review.")
        else:check_approval(plan, approval)
        narrative_checks(plan, timeline, proposals, plan["scene_reviews"])
    raw = {"narrative":plan["narrative"],"outline":plan.get("outline"),"beats":[{k:b[k] for k in Beat.model_fields if k in b} for b in plan["beats"]]}
    checked = validate_storyboard(raw, timeline, proposals, maximum=plan.get("maximum_s",175), require_story=plan.get("mode") != "kill_compilation_baseline")
    beats = checked["beats"]
    captions = remap_captions(beats,timeline["transcript"])
    output.parent.mkdir(parents=True,exist_ok=True)
    # Filters run with cwd=temp; fixed relative names avoid path quoting/injection.
    with tempfile.TemporaryDirectory(prefix=".story-render-",dir=output.parent) as temp:
        temp = Path(temp).resolve()
        def wrapped_text(text,stem,width,size,y,enable):
            # Separate filters avoid a visible newline glyph in some FFmpeg/font builds.
            filters=""
            for line_no,line in enumerate(textwrap.wrap(text,width)):
                name=f"{stem}-{line_no}.txt"
                (temp/name).write_text(line)
                filters+=f",drawtext=textfile={name}:expansion=none:fontcolor=white:fontsize={size}:x=36:y={y+line_no*(size+9)}:enable='{enable}'"
            return filters
        segments = []
        for i,b in enumerate(beats):
            length = b["end_s"]-b["start_s"]
            (temp/"position.txt").write_text(f"{i+1} / {len(beats)}   |   SOURCE {int(b['start_s'])//60}:{int(b['start_s'])%60:02d}")
            prefix,graph = _portrait_filters(info,config)
            heading = "ENCOUNTER COMPILATION" if plan.get("mode") == "kill_compilation_baseline" else "MATCH STORY"
            graph += f",drawtext=text='{heading}':fontcolor=0x9babc6:fontsize=24:x=36:y=44"
            label_start = b["overlay_start_s"]-b["output_start_s"]
            label_end = b["overlay_end_s"]-b["output_start_s"]
            graph += wrapped_text(b["overlay"],"context",30,38,92,f"gte(t,{label_start})*lt(t,{label_end})")
            phase_label = "The opening" if i == 0 else "The finish" if i == len(beats)-1 else "Later in the match"
            graph += f",drawtext=text='{phase_label}':fontcolor=white:fontsize=38:x=36:y=92:enable='lt(t,{label_start})+gte(t,{label_end})'"
            graph += ",drawtext=textfile=position.txt:expansion=none:fontcolor=0x9babc6:fontsize=22:x=36:y=1200"
            if review_preview:
                graph += ",drawtext=text='DRAFT PREVIEW - NOT APPROVED':fontcolor=0xffcc66:fontsize=22:x=36:y=1144:box=1:boxcolor=black@0.45:boxborderw=8"
            bridge=beats[i-1].get("explanation",{}).get("connection_to_next") if i and beats[i-1].get("explanation") else None
            if bridge:
                graph += wrapped_text(bridge["text"],"bridge",45,25,1045,f"lt(t,{min(6,length)})")

            local = [{**c,"start_s":c["start_s"]-b["output_start_s"],"end_s":c["end_s"]-b["output_start_s"]}
                     for c in captions if b["output_start_s"] <= c["start_s"] < c["end_s"] <= b["output_end_s"]]
            if local:
                (temp/"speech.srt").write_text(srt_text(local))
                graph += ",subtitles=speech.srt:force_style='Fontsize=18,MarginV=65,Outline=1'"
            maps = ["-map","0:v:0"]
            if prefix == ["-filter_complex"]:
                graph += "[out]"
                maps = ["-map","[out]"]
            segment = temp/f"shot-{i:02}.mkv"
            cmd = ["ffmpeg","-v","error","-threads","2","-ss",str(b["start_s"]),"-i",str(video.resolve()),
                   "-t",str(length),*prefix,graph,*maps,"-map","0:a:0?",
                   "-c:v","libx264","-threads","2","-preset","veryfast","-crf","21","-pix_fmt","yuv420p"]
            if info["has_audio"]:
                cmd += ["-af", "aresample=48000,apad", "-c:a","pcm_s16le"]
            cmd += ["-y",str(segment)]
            subprocess.run(cmd,cwd=temp,check=True)
            segments.append(segment)
        (temp/"concat.txt").write_text("\n".join(f"file '{s.name}'" for s in segments))
        temporary = temp/"story.mp4"
        subprocess.run(["ffmpeg","-v","error","-f","concat","-safe","1","-i","concat.txt",
                        "-t",str(checked["duration_s"]),"-c:v","copy","-c:a","aac","-b:a","128k",
                        "-movflags","+faststart","-y",str(temporary)],cwd=temp,check=True)
        actual = probe(temporary)
        if not actual["duration"] <= 180 or abs(actual["duration"]-checked["duration_s"]) > .25:
            raise RuntimeError("Export duration failed validation.")
        if (actual["width"],actual["height"]) != (720,1280) or actual["has_audio"] != info["has_audio"]:
            raise RuntimeError("Export dimensions/audio failed validation.")
        temporary.replace(output)
    mapping = [{k:b[k] for k in ["scene_id","start_s","end_s","output_start_s","output_end_s","evidence_ids","overlay","overlay_start_s","overlay_end_s","explanation"]} for b in beats]
    (output.with_suffix(".mapping.json")).write_text(json.dumps({"source":info,"timeline_identity":timeline["identity"],"storyboard_hash":plan_hash(plan),"review_preview":review_preview,"shots":mapping,"captions":captions},indent=2))
    (output.with_suffix(".srt")).write_text(srt_text(captions))
    return {"output":probe(output),"planned_duration_s":checked["duration_s"],"shot_count":len(beats),"caption_count":len(captions),"review_preview":review_preview}


def render_preview(video: Path, start: float, end: float, output: Path) -> dict:
    """A bounded landscape source excerpt for storyboard review, not a final edit."""
    import math
    info=probe(video)
    if not all(math.isfinite(v) for v in [start,end]) or not 0<=start<end<=info["duration"] or end-start>90:
        raise ValueError("Preview must be a source interval of at most 90 seconds.")
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        path=Path(temp)/"preview.mp4"
        subprocess.run(["ffmpeg","-v","error","-ss",str(start),"-i",str(video),"-t",str(end-start),
                        "-vf","scale=960:-2,fps=30","-c:v","libx264","-threads","2","-preset","veryfast","-crf","24",
                        "-c:a","aac","-movflags","+faststart","-y",str(path)],check=True)
        if abs(probe(path)["duration"]-(end-start))>.25:raise RuntimeError("Preview duration mismatch.")
        path.replace(output)
    return probe(output)
