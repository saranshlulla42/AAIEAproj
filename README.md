# Valorant StoryClip

A student prototype that turns local Valorant gameplay into a 30–60 second vertical encounter or a chronological match story up to 175 seconds. The current detector is calibrated to the supplied s0m Clove recording, where the tracked player is named `Me` in the HUD.

## Start the demonstration interface

```bash
.venv/bin/python -m streamlit run app.py
```

Select the recording, scan gameplay, inspect the event evidence, then create a highlight. The first full scan may take several minutes; subsequent matching scans use cached data. The event baseline is explicitly labelled separately from the Pi agent.

## Setup on another machine

Install Python, FFmpeg, ffprobe, Tesseract OCR, and Pi. On Ubuntu, the media/OCR dependencies can be installed with `sudo apt-get install ffmpeg tesseract-ocr`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Start Pi interactively and use `/login` to connect your ChatGPT subscription. Select an available subscription model. The command-line adapter uses the `openai-codex` provider and defaults to `gpt-6-luna`; choose another available image-capable model using `--model` if needed. Usage counts toward the subscription allowance. Credentials remain in Pi's own authentication storage.

Place one input `.webm` or `.mp4` in the project folder. Multiple inputs require `--video` when using the CLI. Different HUDs require recalibration in `hud_config.json`, including player name, known visible opponent names and HUD crop regions. The separate `portrait_layout.json` configures the optional facecam crop; set its `facecam` field to null to use simple padding.

## Command-line workflow

```bash
# Inspect a source frame at 25 seconds.
.venv/bin/python -m storyclip inspect --start 25 --out runs/inspect

# Scan a short section before the full video.
.venv/bin/python -m storyclip scan --start 15 --end 55 --out runs/sample

# Scan the full video; no language-model requests at this stage.
.venv/bin/python -m storyclip scan --out runs/demo

# Full cached scan -> agent tools -> validated edit -> vertical MP4.
.venv/bin/python -m storyclip run --out runs/demo

# Compare against the fixed event-ranking baseline.
.venv/bin/python -m storyclip run --out runs/demo --baseline

# Run the core validation tests.
.venv/bin/python -m unittest discover -s tests -v
```

Use `--video '/absolute/path/to/gameplay.webm'` for an explicit input. Source timestamps are always original-file seconds. A limited scan is not a full-match evaluation.

## Implemented workflow

1. FFmpeg decodes small kill-feed and health crops at two samples per source second.
2. OpenCV identifies colored feed rows. Tesseract reads names and HP; temporal tracking removes persistent feed entries and flags single observations. Close repetitions involving the same killer and victim are flagged for review instead of inflating multi-kill scores; genuine repeat kills after revival also require review.
3. Candidate ranking groups distinct attributed kills within 15 seconds, gives a documented low-HP bonus, and suppresses overlapping proposals.
4. Python calls Pi for a JSON action. Available actions are `get_events`, `get_health`, `inspect_frames`, and `submit_clip`. The controller executes actions and feeds results back on the next bounded turn. Sampled frames are attached when requested.
5. Pydantic and Python enforce evidence references, source bounds, and 30–60 second duration. FFmpeg produces a 720 × 1280 H.264/AAC MP4 preserving the full gameplay frame, with an optional separate facecam panel above it.

The agent gets at most six turns, two evidence requests, and one validation correction. General-purpose Pi tools are disabled for these requests. A failed agent run does not silently become an agent-labelled baseline.

## Inspectable artifacts

Each run saves `scan.json`, `events.jsonl`, `event_index.json`, `health.jsonl`, kill-feed evidence crops, `candidates.json`, model response cache, `agent_trace.json`, `edit_plan.json`, and the output MP4. The event index includes automated repeat flags; it is not a human-verified annotation. Scan cache identity includes the source metadata, detector code, crop configuration, interval, and sampling rate. Subscription-model results are cached by prompt and model. Rendering replaces the final MP4 only after its technical checks pass.

## Current limits

- HUD extraction is fallible perception. `consistent_ocr` means repeated readings, not verified game telemetry or a calibrated probability.
- The detector uses this video's name layout. Overlays, compression, spectator changes, unknown nicknames, and changes to the HUD can cause misses or false positives.
- Low health means displayed HP ≤ 40, joined to a recent consistent observation preceding the detected feed timestamp. OCR can detect an entry late, so this remains a provisional feature until denser event-timing checks are added. Armor and temporary effects are separate. Unknown HP is never treated as zero.
- Sparse frames cannot establish every action or outcome. Watch the final clip before posting; the agent must not invent a clutch, ace, or victory.
- Match Story supports imported speech captions, optional local transcription, and bounded score/event rescans. Headshot/alive-player/death detection and generated narration remain unavailable.
- Sampling reduces detector work but does not eliminate decoding cost for the 60 FPS AV1 source.

This prototype provides game-event evidence and a visible agent/tool loop. Broad highlight quality and detector accuracy require further labelled evaluation.

## Match Story: outline, scene evidence, review, approval

Select **Match Story** and **Plan story for review**. The planner uses `openai-codex/gpt-6-luna`, confirmed in Pi's installed model list. It chooses one narrative thread before selecting cuts, inspects every intended scene, explains its situation/action/consequence, and runs a separate storytelling critique. It produces 3–5 connected beats; 175 seconds is a maximum, not a target.

The app shows a one-paragraph premise, the initial situation, what changes, the resolution, each scene's purpose, cited source images, source-excerpt playback, and evidence-backed bridges. **Preview full draft** assembles the complete edit with original audio and a persistent **DRAFT PREVIEW - NOT APPROVED** watermark, so you can judge the story before approval. Only a draft that passes the AI critique can be previewed. You can save feedback for a fresh planning run. Export stays disabled until you review and approve the exact draft. Changes invalidate approval; requesting a revision revokes it.

Planning uses separate typed requests for the outline, each scene review, scene connections, and critique, with GPT-6 Luna at medium thinking. Python executes frame inspections and assembles the storyboard. Each phase allows three replies to correct validation errors, within a 24-request total limit. One recovery for an unsuitable scene and one revision after critique rejection are available separately, within three planning cycles. Corrections retain the previous candidate and concrete evidence/timing errors. Provider failures are reported separately; eligible temporary failures get up to two retries, after 2 and 4 seconds, within the same phase and total request limits. Progress identifies the current phase; failures show the actual cause and a **Planning diagnostics** trace. Pi's interim commentary is excluded from final JSON parsing. Before/after claims may reuse an earlier observation, and the decisive change may share the final-result sample.

```bash
# Use the existing full-recording timeline; no final video is rendered.
.venv/bin/python -m storyclip story-select --out runs/demo

# Or build the timeline and prepare a story-first draft.
.venv/bin/python -m storyclip story-run --out runs/demo \
  --anchors runs/demo/reviewed_anchors.json

# Read runs/demo/STORY_REVIEW.md and inspect source scenes before approving.
.venv/bin/python -m storyclip story-approve --out runs/demo

# Render only the approved, unchanged storyboard.
.venv/bin/python -m storyclip story-render --out runs/demo

# Optional duration-matched encounter compilation.
.venv/bin/python -m storyclip compare --out runs/demo
```

`story-run` now stops at the draft. The old `storyboard.json` and phase-spanning assisted exports remain historical artifacts; they cannot be approved/exported through the new story workflow. `--assisted` can still write a legacy rule-based draft for inspection, but it does not satisfy the new narrative review requirements.

New artifacts: `story_outline.json`, labelled `story_v2_frames`, `storyboard_draft.json` (including rejection findings), `storyboard_v2.json`, `STORY_REVIEW.md`, `story_v2_agent_trace.json`, `story_feedback.json`, `story_approval.json`, `match_story_draft_preview.mp4`, and the approved `match_story_v2.mp4` plus source/output maps. Preview maps identify the draft and its exact storyboard hash. Model prompts are stored as files to avoid command-line length limits; responses and request durations are cached by model and prompt. Typed requests use `story_v3_model_cache` and `story_v3_review_cache`, separate from the old action-protocol caches.

`score_config.json` holds calibrated HUD score crops. Unknown intervals remain unknown; team identity is local to reviewed anchors, including side changes. Story explanations cannot cite uncertain/repeated events as established facts. The independent critique checks sampled visual support, complete scene cuts, and whether the selected scenes develop the same story. These checks cannot guarantee audience engagement or recover every action missed by sampling.

Score-snapshot overlays expire after five seconds or an earlier accepted score change, so a sampled score does not persist over a later round. Final-result overlays remain through the ending. On-video bridges use plain viewer language; citations and uncertainty remain in the review panel.

Optional speech captions can be imported with `--transcript path.json` or uploaded in the UI. The JSON contains an exact `source` object from `timeline.json`, a `segments` list with `start_s`, `end_s`, and `text`, and optional `offset_s` for window-relative timestamps. Selected references are remapped to output seconds.

For local automatic transcription, install `requirements-transcription.txt`, download a faster-whisper model separately, and use `--transcribe-model /path/to/model-directory`. Downloads are never triggered implicitly. Original audio is preserved. No local speech-recognition model was available during the measured demo. Death attribution remains uncalibrated; there is no generated narration.

See `STORY_FIRST_IMPLEMENTATION.md` for validation results and the pending live Luna draft.
