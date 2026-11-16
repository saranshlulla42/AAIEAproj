# Match Story implementation and measured checks

Implemented on 14 October 2026. Moment Highlight remains available alongside a separate Match Story workflow.

## Delivered

- Full-recording event-cache reuse plus calibrated score OCR, source-bound reviewed anchors, cached source frames, and one refinement pass around score changes/unknown readings.
- A timestamped timeline with stable evidence IDs, quiet/unknown intervals, score boundary brackets, tentative/repeat event flags, health context, optional transcript references, and explicit uncertainty. Team identity is local to reviewed frames, including side changes.
- 19 phase-spanning proposals on the supplied match. Opening, middle, late action, and final-result options survive discovery.
- A strict storyboard schema, evidence-grounded generated overlays, source/output mappings, chronology/overlap/budget checks, team-mapped result validation, and verified progression requirements for stronger narrative labels.
- Pi tools for timeline/interval summaries, cached events, actual transcripts, scene images, bounded denser score/event scans, and validated storyboard submission. Four investigations, at most one dense rescan, and one correction are allowed. A failed model run does not become an agent-labelled assisted result.
- Multi-shot portrait rendering with original audio, remapped optional speech captions, labels timed to observed evidence, technical validation, and atomic replacement of the final video.
- UI mode selection, source evidence, editable cut boundaries, preview/download, and a duration-matched compilation comparison. New CLI commands are documented in README.md.

## Actual recording

The source is the supplied 1,993.088-second s0m Clove recording. The full cached event scan contains 25 OCR-attributed records; this is not a match kill count.

The score pass produced 123 automated observations: 40 consistent OCR readings, 17 requiring review, and 66 unknown. Eight inspected anchors supplement these readings. The ending at 1,980 source seconds visibly shows VICTORY with the top HUD score 13–11 and the tracked player in the winning roster. The scoreboard's round-history score lags the top HUD on the ending frames; the anchor notes record that distinction.

The assisted storyboard selects five shots:

| Role | Source seconds | Output seconds | Context |
|---|---:|---:|---|
| Setup | 0–25 | 0–25 | Reviewed 0–0 opening; label begins at source 5s |
| Early action | 415.5–455.5 | 25–65 | Recorded encounter; uncertain/repeat events remain visible in evidence |
| Development | 1005–1035 | 65–95 | Neutral HUD score 6–5, displayed from source 1020s |
| Late action | 1362–1402 | 95–135 | Neutral HUD score 10–6, displayed from source 1395s |
| Finish | 1953.088–1993.088 | 135–175 | Reviewed victory 13–11, displayed from source 1980s |

This is explicitly an **assisted factual recap**. It uses reviewed anchors and deterministic phase-spanning selection. It is not represented as a live Pi-selected story.

## Verification

- **31 automated tests passed.** Regression and real-media tests cover source bounds/non-finite values, evidence containment, chronology, duration, uncertain score rejection, team mapping, outcome consistency, comeback support, quiet intervals, partial-scan rejection, transcript offsets/remapping, bounded agent feedback/correction/rescans, changed-source rejection, and real multi-shot rendering.
- The real FFmpeg fixture checks red/green/blue cut order and changing 440/660/880 Hz audio across the assembled shots. It also verifies speech-caption mapping and portrait output dimensions.
- The full cached CLI story-run exported a 175-second, 720 × 1280 H.264/AAC video with audio. A kill-ranked compilation uses the same 175-second planned duration.
- Streamlit AppTest found no exceptions in Moment Highlight, Match Story, or assisted planning. Browser testing used the updated local app on port 8502; the pre-existing port 8501 process continued serving its older loaded app.
- Visual frame review found a premature score label. The renderer was corrected to delay score/outcome labels until their evidence timestamps. The early encounter selection was also corrected to use 15-second clusters consistently.

A live Pi run subsequently completed through the open interface: `inspect_scene(scene-18)` → `submit_storyboard`, with a validated 147-second factual recap across six scenes. The exported `runs/demo/match_story.mp4` measures 147.005 seconds, 720 × 1280, H.264/AAC, with original audio. A separate `kill_compilation_agent.mp4` comparison uses the same 147-second planned duration. The UI displayed “Match story ready” and playback was visible in the browser.

The earlier direct Pi CLI command was rejected by automatic approval review because it accesses Pi credentials and sends match-derived evidence externally. The completed app artifacts supplied the live integration evidence; subsequent verification used the saved plan and local rendering. No additional external request was needed. Per-request latency metadata is now recorded alongside newly generated model-cache entries, but exact latency for the already completed run was not measured.

No local speech-recognition model was installed, so the optional faster-whisper inference path has not been tested on this recording. Transcript validation and caption rendering/remapping have been tested. Death detection remains uncalibrated and unavailable; health is never converted into an inferred death. Final result extraction is assisted visual review rather than an automatic victory detector.

## Human comparison to complete

Watch `runs/demo/match_story.mp4` and `runs/demo/kill_compilation_agent.mp4` in shuffled order (147 seconds each), or compare `match_story_assisted.mp4` with `kill_compilation.mp4` (175 seconds each). For each, record the initial situation, how it changed, final outcome, confusing jumps, and engagement (1–5). Check factual answers against the inspected source frames. Record missed/incorrect detector events separately from narrative quality. No superiority or engagement score is claimed before that review.

## Suggested next improvements

1. **Gameplay-first framing:** reduce the large facecam panel and add a selectable gameplay zoom layout. The current full-frame view preserves the HUD but makes action small on a phone.
2. **Better pacing:** shorten buy-phase/context shots and retain complete action/resolution windows. Add thumbnail cards, per-shot playback, and a visual duration bar to make these edits easier than a table of seconds.
3. **More reliable context:** prioritize score OCR calibration, automatic final-screen recognition, and verified player/team identity over extra kill detectors. The many unknown readings are the largest evidence weakness.
4. **Actual commentary captions:** run the optional local speech model, review recognition errors, and prefer useful commentary over quiet filler when choosing scenes.
5. **Measured storytelling evaluation:** collect human comparison answers and a held-out labelled event set before tuning narrative scoring or claiming the agent improves highlights.
