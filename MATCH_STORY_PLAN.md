# Match Story mode — proposed next version

The user's revised goal is to summarize the trajectory of an entire Valorant match in a vertical video lasting up to three minutes. The existing implementation scans the full recording for candidate events but exports one continuous encounter. This document records the requested scope. Match Story mode is now implemented; see `MATCH_STORY_IMPLEMENTATION.md` for the delivered workflow, measured checks, and remaining calibration/integration limits.

## Outcome and story scope

Provide two modes: Moment Highlight (the current 30–60 second encounter) and Match Story (a chronological sequence drawn from the full recording, normally 120–175 seconds).

A match story establishes the situation, shows how it developed, and includes the outcome. It can describe a dominant performance, a difficult match, a comeback, a comeback that failed, a close finish, or an unusual sequence if the footage supports that interpretation. A victory or heroic comeback is not required. The agent must be able to choose a factual recap when evidence does not establish a stronger arc.

The output summarizes the whole match through selected evidence. It cannot retain every event from a 33-minute recording in three minutes. Broad input coverage and a complete narrative are different from showing every round.

YouTube's current help page says square or vertical videos up to three minutes are eligible for Shorts. Target below the upper limit to leave room for transitions and encoding rounding. [YouTube Shorts duration](https://support.google.com/youtube/answer/15424877?hl=en)

## 1. Build a match timeline before selecting scenes

Reuse the existing event and health cache. Add calibrated OCR of the two score numbers near the top of the HUD, plus timestamped sampled images of important state changes. Verify which score belongs to the tracked player before making team-specific claims, including around side changes.

First test score extraction on a few manually inspected frames across the start, middle, and ending. Then make a coarse full-video score pass. Increase sampling around score changes or ambiguous readings. Validate score transitions and retain unknown intervals rather than filling them with guesses. Coarse observations can bracket round boundaries; they do not establish the exact moment of a win.

Represent each observed round or unresolved interval with:

- Source start/end estimates and the evidence used for the estimates.
- Observed score before/after, team mapping, and uncertainty.
- Attributed kills, tentative events, and repeat flags.
- Detected player deaths if the kill-feed can reliably identify the player in the victim position.
- Relevant health observations and source frames.
- Short commentary excerpts where available.

The existing scanner does not extract round state or deaths yet. Deaths, score transitions, and final-outcome evidence need their own calibration and validation.

Keep the timeline as a local JSON artifact, with original-video timestamps and stable evidence IDs. This is the agent's compact map of the recording. It represents quiet and unsuccessful portions too, even when they generate no high-scoring kill candidate.

## 2. Preserve broad coverage during discovery

The present kill-ranked shortlist is useful for encounter highlights but can exclude the opening struggle and final result. Match Story discovery should retain options from early, middle, and late phases, including:

- A scene establishing the initial situation.
- A setback or representative difficult round, if relevant.
- A possible turning point identified from verified score progression.
- Strong action sequences supported by event evidence.
- A closing round or explicit final-result scene.

Create approximately 10–20 scene proposals spanning these functions, not just the largest kill clusters. Each proposal records source interval, relevant timeline evidence, possible role in the story, and uncertainty. The agent chooses a smaller set after inspecting context.

## 3. Add commentary and visible bridges

Transcribe selected candidate windows and adjacent context first if full-recording transcription is too expensive. Add window offsets so transcript timestamps remain original-video seconds. Full transcription is useful later for discovering non-kill stories, but need not block a score-driven recap.

Use original speech captions and short score/context overlays to connect scenes. For example, a verified score label such as “Round 8 — trailing 3–5” can orient a viewer when the edit skips several minutes. This example is illustrative, not a claim about the supplied match.

Generated context labels must cite observed evidence. Do not write invented player dialogue or attribute emotions such as panic without support. Optional narration comes after a captioned storyboard works; a voice-generation service is not required for the deadline version.

## 4. Let the agent make a storyboard

Supply the full timeline, candidate summaries, and available tools. The agent proposes an evidence-grounded narrative and investigates the scenes needed to support it. It produces a storyboard rather than one pair of start/end times.

Each beat contains:

- Its narrative role: setup, development, setback, turning point, action, or outcome.
- A selected source interval.
- Evidence IDs supporting its factual claims.
- A short overlay caption and any speech-caption references.
- Why this scene belongs in the story.
- Unresolved uncertainty and required review.

A plausible duration budget is setup 15 seconds, early development 30, turning point 25, important action 40, finish 35, and payoff 10: 155 seconds total. This is a planning example. The footage determines whether those beats exist and how much time they need. Duration should remain a maximum constraint, not a demand to fill all three minutes.

## 5. Tools and bounded investigation

| Proposed tool | Purpose |
|---|---|
| `get_match_timeline()` | Understand the whole recording's observed progression |
| `get_round_summary(round_id)` | Inspect a relevant round and its uncertainty |
| `get_events(start, end)` | Retrieve cached game-event records |
| `get_transcript(start, end)` | Retrieve actual speech and timestamps |
| `inspect_scene(scene_id)` | Retrieve labelled sampled frames or other supported visual evidence |
| `rescan_interval(start, end)` | Refine event/score timing in a bounded interval |
| `submit_storyboard(beats)` | Validate chronology, grounding, source bounds, and duration |

The first timeline scan is ordinary preprocessing, performed once and cached. The agent chooses which uncertain parts to investigate. Start with a small investigation budget, for example four scene/context requests and one storyboard revision, and measure actual model latency. Increase the budget only if missing evidence prevents useful selection.

One agent can perform the planning and revision; separate role prompts can structure a critique without requiring a multi-agent framework.

## 6. Extend the renderer and validator

Add a separate multi-scene renderer. Individual source shots can be shorter than the current moment renderer's 30-second minimum. Trim, normalize, and concatenate the selected intervals, preserving chronological order and original audio. Add captions or context overlays at the appropriate output times.

Maintain an explicit mapping from each source interval to its output interval. Speech captions must be remapped into the assembled timeline rather than copied with their original offsets.

Validate:

- Every source interval is within the recording and uses finite timestamps.
- Scenes are chronological, non-overlapping, and contain the evidence they cite.
- Selected footage and added cards/transitions fit the total duration budget.
- The final export, measured by ffprobe, remains within the three-minute limit.
- Output dimensions, video/audio streams, and caption timing are correct.
- Team-specific score and outcome claims have verified team mapping.
- A comeback claim is supported by observed progression; otherwise use a neutral recap.

Avoid automatically stitching together every highly ranked kill clip. Story planning must choose what establishes context and what changes the situation.

## 7. Build order for the remaining deadline

1. Extract and manually verify start/middle/final score observations. Build the timeline JSON. A few manually verified anchor records are acceptable for a clearly labelled assisted demo if automated round extraction remains unreliable.
2. Combine those anchors with cached kills and phase-spanning scene candidates.
3. Implement the storyboard schema and agent tools, including final-outcome investigation.
4. Implement chronological multi-scene rendering and remap captions/context labels.
5. Add a Match Story option to the interface and show the storyboard and source evidence.
6. Watch the assembled output and revise cuts that lose the situation or resolution.

Timebox detector improvements. Broad score/outcome context and coherent editing are higher priorities for this mode than adding every possible game-event detector. Reuse the existing scan, Pi connection, evidence storage, portrait layout, and technical export checks.

## 8. Evaluate the revised goal

Compare a duration-matched kill compilation with the planned match story. Ask a reviewer to describe the initial situation, how it changed, and the final outcome after watching each. Record whether those answers agree with manually verified footage, whether captions bridge the time jumps, and whether the video remains engaging.

Report discovery misses and unsupported claims separately from storytelling quality. Sparse image sampling and OCR cannot guarantee understanding of every action. A human should verify the final story against the source before presentation or publication.

The immediate next engineering milestone is a verified match timeline with score progression and final-outcome evidence. That unlocks the global storyboard; merely lengthening the existing continuous clip does not.
