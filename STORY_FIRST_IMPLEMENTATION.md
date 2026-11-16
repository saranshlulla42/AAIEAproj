# Story-first workflow

## Model check

The previous application defaults and the saved live storyboard used `gpt-6-sol`. Pi's installed model list confirms `openai-codex/gpt-6-luna` with image support. The Moment Highlight adapter, Match Story planner, and CLI defaults now use `gpt-6-luna`. The app passes this explicit model to Pi; unrelated global Pi settings are not changed.

## What changed

The earlier workflow enforced chronology and broad coverage but allowed disconnected scores and action. It could inspect only the final scene and submit the rest from summaries. The new workflow requires:

1. A grounded outline first: a one-paragraph premise, viewer question, initial situation, important change, resolution, and 3–5 scene intentions.
2. Inspection of every intended scene, including wider context around original proposals. Labelled source frames retain original timestamps and stable evidence IDs.
3. A visual review of each scene: situation, action, consequence, uncertainty, and whether the selected interval is useful and complete. Each factual explanation must cite inspected source images; tentative scores/repeat events cannot support established claims.
4. A storyboard implementing the accepted outline. Every scene has a specific question and purpose, and a short bridge citing evidence from both adjacent scenes. Cuts must preserve reviewed facts and the three core facts of the outline.
5. A fresh-role model critique assessing whether viewers can understand the situation, change and resolution. A technically valid edit can fail this critique. Rejection findings are saved. One recovery for an unsuitable scene and one revision after critique rejection are available separately, within three planning cycles; repeated rejection never enables export.
6. Human review and exact-plan approval. The UI shows explanations, source images, scene playback, critique findings, and a full draft preview with original audio and a persistent review watermark. Feedback revokes approval and requires a fresh draft. Plan hashes invalidate approval after edits. CLI story-run also stops at the draft.

The renderer burns short bridges into the assembled video, preserves source speech, and retains the existing technical checks. Source excerpts and the watermarked full draft are available before approval. An unmarked final export still requires exact-plan approval. Score-snapshot captions expire within five seconds or an earlier accepted score change. Wrapped on-video text uses separate line filters to avoid visible newline glyphs in the local FFmpeg build. There is no target duration to fill.

## Validation

**68 automated tests passed.** The automated suite covers the original detector/edit checks and the new narrative controller, source inspection, missing/unrelated bridges, unreviewed facts, failed critique, approval invalidation, feedback revocation, UI export gating, and model defaults. The real-media test also exercises an approved synthetic storyboard and bridge rendering, with colour/tone cut-order checks and source/output mapping. Regressions cover per-phase correction budgets, precise failure reporting, early rejection of late-only outlines, reused before/after evidence, shared decisive-change/result samples, Pi interim/final response parsing, provider failure classification/retry, source-scene recovery followed by a separate critique revision, cut-duration reservation for the ending, short-lived score overlays, and draft-preview gating/watermark rendering.

The controlled model responses test orchestration and failure handling; they do not prove that Luna will choose an engaging story on this recording. Structural checks and an AI critique cannot mathematically guarantee narrative quality. The user's source-scene review remains the last step before export.

## Planning failure correction

The user-triggered run stopped after three invalid replies, before any scene inspection. Its generic budget message hid two concrete failures: the model emitted several JSON actions in one reply, and chronology validation treated the earliest before/after citation as the change timestamp. Pi also exposes interim/final text phases in `textSignature`; the adapter had concatenated these blocks.

The controller now sends one schema per phase (outline, scene review, connections, critique). Python performs inspections and assembles the final storyboard. Corrections apply to the failing phase: three replies per phase, 24 total requests, one source-scene recovery, and one critique revision. Story requests explicitly use medium thinking. Dense rescans supplement sparse evidence once; cut allocation reserves the core facts and final buildup. The model sees the previous rejected draft and concrete validation errors rather than starting each correction blind. The initial payload for this saved timeline decreased from 125,240 to 36,002 bytes. Invalid reply text is saved locally rather than copied into subsequent prompts. JSON parsing uses the final response and excludes interim commentary. Chronology uses the latest supporting timestamp, permits a decisive change and resolution to share a sampled frame, and still requires the initial situation to precede the change. Failures now record their phase and cause and appear in the UI diagnostics.

A live Pi / GPT-6 Luna format check with `ready=true` passed. A second live check returned a valid three-scene outline on its first attempt using entirely fictional scores, scene IDs and timestamps. Neither check included the recording, its frames, or its timeline. These checks verify response handling and outline generation; they do not establish scene-selection quality on the actual recording.

## Authorized actual-recording retest — completed

The user explicitly authorized sending this recording's timeline and sampled gameplay frames to OpenAI through Pi/GPT-6 Luna. The authorized live run produced a three-beat draft and passed the separate storytelling critique. Two further fresh critiques passed after source review shortened stale score captions, removed an ambiguous subtitle quotation, and rewrote the on-video bridges in plain language. These editorial changes are recorded in the storyboard; source cuts and core facts remain unchanged. The final state is `awaiting_human_review`, with 17 requests recorded.

The draft lasts **119.526 seconds** and uses these source intervals:

| Beat | Source seconds | Story purpose |
|---|---|---|
| Setup | 16.757–50.000 | Opening player eliminations and a visible round-win banner |
| Setback | 943.800–990.000 | Another credited elimination, followed by a teammate spectating view |
| Outcome | 1945.917–1986.000 | Final planted-spike encounter, teammate finish, and confirmed 13–11 victory |

The current timeline contains 168 score observations and eight reviewed anchors. Three source-excerpt previews were rendered and verified for duration and audio. The complete watermarked draft is `runs/demo/match_story_draft_preview.mp4`: 720 × 1280, 119.526 seconds, with original audio. Its map records the exact storyboard hash and `review_preview=true`. No approval receipt was created for the real recording and no unmarked final export was generated. The app presents this saved draft; another planning run is unnecessary just to review it.

The regression suite includes real synthetic multi-shot rendering with cut-order, audio-tone, captions, bridges, and watermark checks. The actual draft also passed source/timeline identity, cut/evidence, and narrative validation, and the app's export remains disabled before human approval. Evidence is saved in `runs/planning_fix_validation.json`, `runs/planning_fix_tests.log`, `runs/demo/source_preview_validation.json`, `runs/demo/draft_preview_metrics.json`, and `runs/demo/STORY_REVIEW.md`. Earlier rejected drafts and failure traces remain historical diagnostics.

This is a connected player-focused recap, not evidence that the edit is engaging to an audience. The model critiques sparse frames, not every intervening action or the continuous audio. The middle excerpt includes a subscriber overlay that obscures action. The full draft preview lets the user judge pacing, clarity, and the strength of the story before approving or requesting revision.

## Suggested next improvements

- Detect player death, spectating transitions, spike state, and round-end banners directly, then sample more densely around those transitions. This would give scene selection clearer action/consequence boundaries and reduce reliance on score snapshots.
- Give gameplay more of the portrait canvas, with a smaller optional facecam. The current layout makes gameplay/HUD details small and retains the source's embedded facecam and alerts.
- Add optional commentary transcription to find intent, tension, and reactions in the audio. Keep evidence-backed event selection and test narrative quality with human reviews, rather than treating an AI critique pass as an engagement score.

## Course-demo readiness check — 14 October 2026

The live app and both cached workflows were checked again. Moment Highlight has available candidates and a saved preview; Match Story has three source excerpts, the full draft preview, and disabled export before approval. Source identity, narrative/cut validation, and preview mapping pass. No new model requests or real-recording approvals were made during this check.

The review found a backend approval gap: the saved story-first draft carries the generic `match_story` mode label, while the renderer previously applied its approval guard only to two other mode labels. The renderer now enforces story-first review and approval whenever `planning_version == 2`, independently of the display mode. A regression test covers generic and compilation mode labels, and the actual saved draft was verified to stop before FFmpeg without approval. **69 automated tests now pass.** Latest checks are saved in `runs/course_demo_validation.json` and `runs/course_demo_tests.log`.

The defensible presentation scope is an assisted MVP on the calibrated recording. The current draft includes reviewed anchors and recorded editorial adjustments. The Moment Highlight mode demonstrates model-selected evidence tools; Match Story demonstrates a host-controlled planning, review, and revision workflow. Evidence-linked explanations and execution traces support auditability, but do not reveal the model's internal reasoning or establish accuracy across other recordings.


## Pi connection recovery — 14 October 2026

A user planning run saved `fetch failed` provider errors. A fresh tiny GPT-6 Luna diagnostic and the exact failing scene-18 request (11 previously authorized source frames) both completed successfully on retest. This establishes current connectivity; the logs do not identify the underlying network fault. No security settings or credentials were changed.

The controller now waits 2 and 4 seconds before up to two eligible provider retries, within the existing three replies per phase and 24-request total. Transport failures remain separate from model corrections. Quota/authentication/input errors and aborted requests stop without retry. The adapter also recognises provider errors when Pi exits nonzero and explains connection failures while preserving cached scans. The actual running app was restarted to load the fix. **71 automated tests pass**, including recovery after two transport failures and stopping after three. Live retest details are in `runs/connection_check/failed_request_retest.log`; tests are in `runs/connection_fix_tests.log`.
