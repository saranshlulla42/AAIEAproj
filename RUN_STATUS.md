# First prototype — measured run

Tested on 14 October 2026 with the locally supplied s0m Clove `.webm` recording.

| Item | Actual result |
|---|---|
| Source | 1,993.088 seconds (33.2 minutes), 1920 × 1080, AV1 at 60 FPS with Opus audio |
| Full scan | 3,986 sampled HUD frames at 2 FPS; 526.93 seconds (8.8 minutes) |
| Raw event records | 25 attributed OCR records; not a verified match kill count |
| Conservative event filtering | 4 close repeated entries flagged for review; only repeatedly observed, unflagged entries contribute to ranking |
| Shortlist | 6 distinct candidate encounters |
| Health | 3,273 of 3,986 sampled readings accepted by temporal consistency; this is coverage, not accuracy |
| Agent connection | Pi subscription OAuth, `openai-codex`, `gpt-6-sol` |
| Actual final action sequence | `inspect_frames` → `get_events` → `submit_clip` |
| Selected interval | 420.5–450.5 source seconds (7:00.5–7:30.5), 30 seconds |
| Output | `runs/demo/highlight.mp4`, 720 × 1280, H.264 video with AAC audio |
| Baseline | `runs/demo/baseline.mp4`, same candidate with fixed 45-second boundaries |
| Core tests | 6 passed |
| Interface test | No Streamlit test exceptions; candidates, scan metrics, and video element present |

The final reason references two accepted HUD event IDs, `kill-0007` and `kill-0008`. The agent sees four sampled images and event tool results; it does not watch continuous video or hear the audio. It explicitly excluded the repeated Cypher entry. The exported interval contains both cited detection timestamps and passes duration, dimensions, and audio-preservation checks.

## Evidence and limitations

- On a manually inspected early section, the scanner found two player-kill events and exported a 45-second clip. Another section containing a kill and the player's death yielded one tentative player-kill record; the death was not attributed as a player kill. This is a limited check, not a detector accuracy benchmark.
- OCR interruptions can make one persistent entry look like another event. Close repeat pairs are conservatively flagged. This may also flag a genuine repeat kill after revival, so those cases require review.
- No low-HP kill was accepted in this run. Low displayed HP was observed elsewhere, but that does not demonstrate accurate low-HP kill classification. Health is currently joined to the detected feed timestamp, which can lag the real elimination. Denser timing checks are needed before treating this feature as verified.
- The agent-selected clip is shorter than the baseline. A preference comparison must account for the 30 versus 45-second lengths; no improvement score has been claimed.
- An earlier agent run demonstrated a validation correction for missing evidence IDs. A later malformed response containing multiple actions was rejected. The format instructions and regression test were strengthened, and the final tested run completed with one action per turn.
- Speech transcription and captions are not yet implemented. Kill/headshot/clutch/win labels are not inferred from audio or sparse screenshots alone.

## What to do next

1. Open the local app at `http://127.0.0.1:8501` and watch the entire agent-selected clip with audio.
2. Check that the beginning establishes the situation, the action is visible, and the ending includes an understandable outcome. Inspect the cited kill-feed crops.
3. Mark missed/incorrect events on a reserved section before adding detectors. Use that to tune the scanner rather than reporting the video's title as ground truth.
4. Prioritize commentary transcription and captions if the core clip is useful. Prepare the course explanation around the real event cache, tool trace, validation, baseline, and known limitations.

Source video and generated run artifacts are ignored by Git. Authentication credentials remain outside the project in Pi's own storage.


## Match Story follow-up — 14 October 2026

Match Story is now implemented alongside Moment Highlight. The updated app used for browser tests is running at http://127.0.0.1:8502/.

- 31 automated tests passed, including real multi-shot video/audio and caption timing checks.
- Full timeline: 131 observations, including eight reviewed anchors; 19 scene proposals.
- Assisted story: five shots, 175.004 seconds, 720 × 1280 H.264/AAC with original audio.
- Live Pi storyboard: six shots, 147 seconds planned; the agent inspected final-result frames and submitted a validated factual recap in two turns. The export measures 147.005 seconds.
- Separate duration-matched compilations are available for each story.
- Visual review corrected early score/outcome overlays; labels now begin at their cited observation times.
- Score/outcome/team mapping remains partly assisted. Death extraction is unavailable. Optional local ASR inference needs a downloaded model and was not tested; imported speech timing and captions were tested.

See MATCH_STORY_IMPLEMENTATION.md for the full evidence, limitations, approval-review history, and improvement suggestions. No human preference/engagement score has been claimed.


## Story-first revision — 14 October 2026

Pi's application and CLI defaults are now `gpt-6-luna`, verified in the installed Pi catalog. The revised workflow selects a narrative before scenes, inspects every intended scene, records situation/action/consequence and adjacent-scene bridges, runs a storytelling critique, and requires exact-plan human approval before export. Feedback revokes approval. Previous exports remain historical results.

44 automated tests passed, including UI approval/feedback gating and a real-media synthetic story with bridge rendering. The actual recording's live Luna draft is pending explicit approval to transfer its timeline and sampled gameplay frames to OpenAI through Pi; automatic approval review rejected that transfer. No new full match video was rendered.

Details: STORY_FIRST_IMPLEMENTATION.md. The prepared request at runs/demo/PI_STORY_REQUEST.json has now been updated to the typed outline protocol below; this prepared request has not been sent.

## Story planning failure fix — 14 October 2026

The user's live run failed after three replies before inspecting footage. Multiple-action replies and an overly strict chronology check were reported as a generic exhausted budget. The controller now uses separate outline/scene/connection/critique schemas, host-managed inspections, per-phase corrections, and precise failure diagnostics. Pi interim commentary is excluded from final JSON parsing. Before/after score citations and a shared decisive-change/result sample are accepted while preserving evidence, critique, and human-approval requirements.

51 automated tests passed. Live GPT-6 Luna checks passed for a format-only request and a fictional three-scene outline (first attempt). No actual gameplay data was sent for those checks. Automatic approval review blocked the actual-recording retest because explicit authorization to resend its timeline and sampled frames to OpenAI through Pi was missing. The earlier user-triggered failure trace is preserved at runs/demo/failure_before_protocol_fix.json. No new actual-recording storyboard or export is claimed.


## Authorized live story retest and draft preview — 14 October 2026

The user authorized transfer of the recording's timeline and sampled frames to OpenAI through Pi/GPT-6 Luna. The revised planner now completed the actual recording: three connected beats, 119.526 seconds, and a passing storytelling critique. After source review corrected score-caption persistence, removed an ambiguous subtitle quotation, and simplified two bridges, two fresh Luna critiques also passed. The run records 17 requests at medium thinking and stops at `awaiting_human_review`.

68 automated tests pass, including real multi-shot video/audio, wrapped bridges, review-preview watermark/gating, and exact-plan approval enforcement. Three source previews and the full 720 × 1280 watermarked draft with original audio are available in the app at http://127.0.0.1:8502/. The current timeline has 168 observations and eight reviewed anchors. The actual draft passes source identity, cut/evidence, and narrative validation. No real-recording approval receipt or unmarked final export was created. The earlier blocked/pending entries above describe historical runs and are superseded by this authorized result.

Watch the full draft before approving the storyboard. Its recurring player thread connects the opening, later setback, and teammate finish; the middle source still contains a subscriber alert. No human engagement score is claimed. See STORY_FIRST_IMPLEMENTATION.md and runs/demo/STORY_REVIEW.md for evidence and improvements.
