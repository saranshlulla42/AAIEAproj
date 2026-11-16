from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from .agent import choose
from .candidates import flag_repeated_entries, propose
from .detectors import scan
from .media import frame, probe, render


def main() -> None:
    parser = argparse.ArgumentParser(description="Valorant StoryClip: inspectable HUD events and agent editing")
    parser.add_argument("command", choices=["inspect", "scan", "select", "render", "run", "timeline", "story-select", "story-render", "story-run", "story-approve", "compare"])
    parser.add_argument("--video", type=Path)
    parser.add_argument("--config", type=Path, default=Path("hud_config.json"))
    parser.add_argument("--layout", type=Path, default=Path("portrait_layout.json"))
    parser.add_argument("--out", type=Path, default=Path("runs/demo"))
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--fps", type=float)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--baseline", action="store_true", help="Use top candidate directly; explicitly non-agentic")
    parser.add_argument("--score-config", type=Path, default=Path("score_config.json"))
    parser.add_argument("--anchors", type=Path, help="Reviewed source-bound score anchors; marks the timeline assisted")
    parser.add_argument("--transcript", type=Path, help="Source-bound speech transcript JSON")
    parser.add_argument("--transcribe-model", type=Path, help="Downloaded local faster-whisper model directory")
    parser.add_argument("--assisted", action="store_true", help="Write a legacy assisted draft only; it cannot be approved/exported as a story")
    parser.add_argument("--storyboard", type=Path, help="Storyboard file for story-render")
    args = parser.parse_args()
    if args.video is None:
        videos = list(Path.cwd().glob("*.webm")) + list(Path.cwd().glob("*.mp4"))
        if len(videos) != 1:
            parser.error("Specify --video when there isn't exactly one input video in the folder.")
        args.video = videos[0]
    info = probe(args.video)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command in {"timeline", "story-select", "story-render", "story-run", "story-approve", "compare"}:
        run_story(args, info)
        return
    if args.command == "inspect":
        (args.out / "source.json").write_text(json.dumps(info, indent=2))
        frame(args.video, args.start, args.out / "frame.png")
        print(json.dumps(info, indent=2))
        return
    if args.command in {"scan", "run"}:
        config = json.loads(args.config.read_text())
        result = scan(args.video, config, args.out, start=args.start, end=args.end, fps=args.fps)
        events = flag_repeated_entries(result["events"])
        (args.out / "event_index.json").write_text(json.dumps(events, indent=2))
        candidates = propose(events, info["duration"])
        (args.out / "candidates.json").write_text(json.dumps(candidates, indent=2))
        print(json.dumps({"metrics": result["metrics"], "candidate_count": len(candidates)}, indent=2))
        if args.command == "scan":
            return
    if args.command in {"select", "run"}:
        result = json.loads((args.out / "scan.json").read_text())
        if result["manifest"]["source"] != info:
            raise ValueError("Cached scan belongs to a different or changed video.")
        candidates = json.loads((args.out / "candidates.json").read_text())
        events = flag_repeated_entries(result["events"])
        candidates = propose(events, info["duration"])
        if args.baseline:
            if not candidates:
                raise ValueError("No validated candidates to export.")
            candidate = candidates[0]
            plan = {"start_s": candidate["start_s"], "end_s": candidate["end_s"],
                    "candidate_id": candidate["id"], "mode": "event_baseline", "needs_human_review": True}
            (args.out / "baseline_plan.json").write_text(json.dumps(plan, indent=2))
        else:
            plan = choose(candidates, events, result["health"], info["duration"], args.out, model=args.model, video=args.video)
        print(json.dumps(plan, indent=2))
        if args.command == "select":
            return
    if args.command == "render":
        if args.end is None:
            parser.error("render requires --start and --end")
        plan = {"start_s": args.start, "end_s": args.end, "mode": "manual_render_test"}
    output = args.out / ("baseline.mp4" if args.baseline else "highlight.mp4")
    started = time.monotonic()
    layout = json.loads(args.layout.read_text()) if args.layout.exists() else None
    actual = render(args.video, plan["start_s"], plan["end_s"], output, config=layout)
    (args.out / "render_metrics.json").write_text(json.dumps({"output": actual, "render_s": time.monotonic()-started}, indent=2))
    print(f"Saved clip: {output.resolve()}")



def run_story(args, info: dict) -> None:
    from .timeline import build_timeline, prepare_timeline
    from .story import assisted_story, choose_story, compilation_baseline, propose_scenes
    from .transcript import import_transcript, transcribe_windows
    from .media import render_story
    from .narrative import approve_storyboard
    started = time.monotonic()
    if args.command in {"timeline", "story-run"}:
        result = scan(args.video, json.loads(args.config.read_text()), args.out)
        transcript = import_transcript(args.transcript, info) if args.transcript else None
        timeline = prepare_timeline(args.video,result,json.loads(args.score_config.read_text()),args.out,anchors=args.anchors,transcript=transcript)
        scenes = propose_scenes(timeline)
        if args.transcribe_model:
            # Merge adjacent discovery windows; preserve original-video offsets.
            windows = []
            for scene in scenes:
                a,b = max(0,scene["start_s"]-3),min(info["duration"],scene["end_s"]+3)
                if windows and a <= windows[-1][1]:
                    windows[-1] = (windows[-1][0],max(b,windows[-1][1]))
                else:
                    windows.append((a,b))
            speech = transcribe_windows(args.video,info,windows,args.out,args.transcribe_model)
            timeline = build_timeline(info,result,timeline["observations"],transcript=speech)
            (args.out/"timeline.json").write_text(json.dumps(timeline,indent=2))
            scenes = propose_scenes(timeline)
        (args.out/"scenes.json").write_text(json.dumps(scenes,indent=2))
        print(f"Timeline: {len(timeline['observations'])} observations, {len(scenes)} scenes")
        if args.command == "timeline":
            return
    else:
        timeline = json.loads((args.out/"timeline.json").read_text())
        if timeline["source"] != info:
            raise ValueError("Timeline belongs to a different or changed recording.")
        scenes = propose_scenes(timeline)
    if args.command == "story-approve":
        plan_path=args.storyboard or args.out/"storyboard_v2.json"
        plan=json.loads(plan_path.read_text())
        if plan["source"]!=info or plan["timeline_identity"]!=timeline["identity"]:
            raise ValueError("Story approval requires this source and current timeline.")
        (args.out/"story_approval.json").write_text(json.dumps(approve_storyboard(plan),indent=2))
        print("This exact storyboard is approved for export.")
        return
    if args.command == "compare":
        plan_path = args.storyboard or args.out/("assisted_storyboard.json" if args.assisted else "storyboard_v2.json")
        target = json.loads(plan_path.read_text())["duration_s"]
        plan,scenes = compilation_baseline(timeline,target)
        (args.out/"compilation_plan.json").write_text(json.dumps(plan,indent=2))
        (args.out/"compilation_scenes.json").write_text(json.dumps(scenes,indent=2))
    elif args.command in {"story-select", "story-run"}:
        if args.assisted:
            plan = assisted_story(timeline,scenes)
            plan_path = args.out/"assisted_storyboard.json"
            plan_path.write_text(json.dumps(plan,indent=2))
        else:
            plan = choose_story(timeline,scenes,args.out,video=args.video,model=args.model,
                                score_config=json.loads(args.score_config.read_text()),scan=json.loads((args.out/"scan.json").read_text()),hud_config=json.loads(args.config.read_text()))
        print(json.dumps(plan,indent=2))
        print("Legacy assisted draft saved; use Pi story-first planning for an approvable story." if args.assisted else "Draft saved. Read STORY_REVIEW.md, then approve the storyboard before story-render. No full video was rendered.")
        return
    else:
        plan_path = args.storyboard or args.out/("assisted_storyboard.json" if args.assisted else "storyboard_v2.json")
        plan = json.loads(plan_path.read_text())
    output = args.out/("kill_compilation.mp4" if plan["mode"] == "kill_compilation_baseline" else "match_story_assisted.mp4" if plan["mode"] == "assisted_match_story" else "match_story_v2.mp4")
    layout = json.loads(args.layout.read_text()) if args.layout.exists() else None
    receipt_path=args.out/"story_approval.json"
    receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    actual = render_story(args.video,plan,output,timeline=timeline,proposals=scenes,config=layout,approval=receipt)
    actual["elapsed_s"] = round(time.monotonic()-started,2)
    (args.out/("compilation_render_metrics.json" if plan["mode"] == "kill_compilation_baseline" else "story_render_metrics.json")).write_text(json.dumps(actual,indent=2))
    print(f"Saved match story: {output.resolve()}")

if __name__ == "__main__":
    main()
