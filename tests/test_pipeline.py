import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from storyclip.agent import choose, invoke_pi, final_response_text, PiRequestError
from storyclip.candidates import flag_repeated_entries, propose


def kill(event_id, timestamp, *, low=False):
    return {"id": event_id, "time_s": timestamp, "victim": "Sova", "displayed_hp_before": 25 if low else 100,
            "low_health": low, "status": "consistent_ocr", "observations": 3}


class PipelineTests(unittest.TestCase):
    def test_story_reasoning_effort_is_applied_and_cache_specific(self):
        from subprocess import CompletedProcess
        record={"type":"message_end","message":{"role":"assistant","stopReason":"stop","content":[{"type":"text","text":"{\"ready\":true}"}]}}
        process=CompletedProcess([],0,stdout=json.dumps(record),stderr="")
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.agent.subprocess.run",return_value=process) as run:
            invoke_pi({"thinking":"medium"},"test-model",Path(temp))
            command=run.call_args.args[0]
            self.assertEqual(command[command.index("--thinking")+1],"medium")
            invoke_pi({"thinking":"low"},"test-model",Path(temp))
            self.assertEqual(run.call_count,2)
            command=run.call_args.args[0]
            self.assertEqual(command[command.index("--thinking")+1],"low")

    def test_pi_interim_text_is_not_concatenated_into_the_final_json(self):
        message={"content":[
            {"type":"text","text":"{\"action\":\"inspect_scene\"} (analysis)","textSignature":json.dumps({"v":1,"id":"interim","phase":"commentary"})},
            {"type":"text","text":"{\"ready\":true}","textSignature":json.dumps({"v":1,"id":"final","phase":"final_answer"})}]}
        self.assertEqual(json.loads(final_response_text(message)),{"ready":True})

    def test_legacy_text_chunks_are_preserved_and_interim_only_is_not_an_answer(self):
        self.assertEqual(final_response_text({"content":[{"type":"text","text":"{\"ready\":"},{"type":"text","text":"true}"}]}),'{'+'"ready":true}')
        self.assertEqual(final_response_text({"content":[{"type":"text","text":"{}","textSignature":json.dumps({"v":1,"id":"interim","phase":"commentary"})}]}),'')

    def test_multiple_model_actions_are_rejected_and_saved_for_diagnosis(self):
        record = {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop",
                  "content": [{"type": "text", "text": '{}{}'}]}}
        from subprocess import CompletedProcess
        process = CompletedProcess([], 0, stdout=json.dumps(record), stderr="")
        with tempfile.TemporaryDirectory() as temp, patch("storyclip.agent.subprocess.run", return_value=process):
            with self.assertRaises(ValueError):
                invoke_pi({}, "test-model", Path(temp))
            self.assertEqual(len(list(Path(temp).glob("*.invalid.txt"))), 1)

    def test_provider_failure_keeps_actual_reason_and_does_not_retry_quota(self):
        from subprocess import CompletedProcess
        record={"type":"message_end","message":{"role":"assistant","stopReason":"error","errorMessage":"Usage limit reached; quota exhausted.","content":[]}}
        process=CompletedProcess([],0,stdout=json.dumps(record),stderr="")
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.agent.subprocess.run",return_value=process):
            with self.assertRaises(PiRequestError) as error:invoke_pi({},"test-model",Path(temp))
            self.assertFalse(error.exception.retryable)
            self.assertIn("quota exhausted",str(error.exception))
            failure=json.loads(next(Path(temp).glob("*.failure.json")).read_text())
            self.assertEqual(failure["errorMessage"],record["message"]["errorMessage"])

    def test_fetch_failure_is_actionable_and_nonzero_exit_is_retryable(self):
        from subprocess import CompletedProcess
        for returncode in (0,1):
            record={"type":"message_end","message":{"role":"assistant","stopReason":"error","errorMessage":"fetch failed","content":[]}}
            process=CompletedProcess([],returncode,stdout=json.dumps(record),stderr="")
            with tempfile.TemporaryDirectory() as temp,patch("storyclip.agent.subprocess.run",return_value=process):
                with self.assertRaises(PiRequestError) as error:invoke_pi({},"test-model",Path(temp))
                self.assertTrue(error.exception.retryable)
                self.assertIn("local scan remains cached",str(error.exception))

    def test_ocr_interruption_does_not_turn_a_repeated_victim_into_a_multi_kill(self):
        first, repeat, other = kill("a", 40), kill("b", 44), kill("c", 45)
        other["victim"] = "Cypher"
        events = flag_repeated_entries([first, repeat, other])
        self.assertEqual(events[1]["status"], "repeat_needs_review")
        self.assertEqual(events[1]["possible_duplicate_of"], "a")
        self.assertEqual(propose(events, 120)[0]["cluster_kills"], 2)

    def test_clusters_are_distinct_and_uncertain_events_do_not_inflate_counts(self):
        events = [kill("a", 40), kill("b", 43, low=True), kill("c", 160)]
        uncertain = kill("d", 44)
        uncertain["status"] = "needs_review"
        candidates = propose(events+[uncertain], 240)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["cluster_kills"], 2)
        self.assertNotIn("d", candidates[0]["event_ids"])
        self.assertTrue(all(30 <= c["end_s"]-c["start_s"] <= 60 for c in candidates))

    def test_end_of_video_still_yields_valid_boundaries(self):
        candidate = propose([kill("a", 175)], 180)[0]
        self.assertGreaterEqual(candidate["start_s"], 0)
        self.assertLessEqual(candidate["end_s"], 180)
        self.assertGreaterEqual(candidate["end_s"]-candidate["start_s"], 30)

    def test_tool_feedback_and_grounded_submission_are_logged(self):
        events = [kill("a", 40)]
        candidates = propose(events, 120)
        candidate = candidates[0]
        replies = [{"action": "get_events", "candidate_id": candidate["id"], "reason": "Inspect evidence"},
                   {"action": "submit_clip", "candidate_id": candidate["id"], "start_s": candidate["start_s"],
                    "end_s": candidate["end_s"], "evidence_ids": ["a"], "reason": "A recorded encounter"}]
        with tempfile.TemporaryDirectory() as temp, patch("storyclip.agent.invoke_pi", side_effect=replies):
            plan = choose(candidates, events, [], 120, Path(temp))
            trace = json.loads((Path(temp)/"agent_trace.json").read_text())
            self.assertEqual(len(trace), 2)
            self.assertEqual(trace[0]["tool_result"][0]["id"], "a")
            self.assertEqual(plan["mode"], "pi_subscription_agent")

    def test_fabricated_evidence_cannot_produce_an_edit_plan(self):
        events = [kill("a", 40)]
        candidate = propose(events, 120)[0]
        invalid = {"action": "submit_clip", "candidate_id": candidate["id"], "start_s": 28, "end_s": 73,
                   "evidence_ids": ["made-up"], "reason": "Unsupported"}
        with tempfile.TemporaryDirectory() as temp, patch("storyclip.agent.invoke_pi", return_value=invalid):
            with self.assertRaises(RuntimeError):
                choose([candidate], events, [], 120, Path(temp))
            self.assertFalse((Path(temp)/"edit_plan.json").exists())


if __name__ == "__main__":
    unittest.main()
