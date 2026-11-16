import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from storyclip.narrative import approve_storyboard, check_approval, critique_passed, narrative_checks
from storyclip.story import choose_story, validate_storyboard, Beat


def pass_review():
    return {"verdict":"pass","initial_situation_clear":True,"change_clear":True,"outcome_clear":True,
            "scenes_connected":True,"claims_supported":True,"cuts_complete":True,"findings":[],
            "summary":"The controlled fixture has connected setup, development and resolution with cited visual evidence."}


def outline_for(scenes):
    return {"premise":"A controlled match starts even, changes in the middle, and finishes with a supported result.",
            "viewer_question":"How does the situation change before the final result?",
            "initial_situation":{"text":"The opening scoreboard is even.","evidence_ids":["a0"]},
            "important_change":{"text":"The middle score changes the situation.","evidence_ids":["a1"]},
            "resolution":{"text":"The final reviewed result is a victory.","evidence_ids":["a2"]},
            "intents":[{"scene_id":s["id"],"role":s["possible_role"],"question":f"What does scene {i+1} change in this match?",
                        "purpose":f"Scene {i+1} establishes a specific part of the same match thread."} for i,s in enumerate(scenes)]}


def scripted_editor(timeline,scenes, *, critic=None, omit_review=False):
    outline=outline_for(scenes)
    def reply(payload,model,cache_dir,*,system):
        stage=payload["stage"]
        if stage=="critique":return critic or pass_review()
        if stage=="outline":return outline
        if stage=="scene":
            inspection=payload["inspection"];frames=inspection["frames"]
            return {"scene_id":inspection["scene_id"],"start_s":inspection["start_s"],"end_s":inspection["end_s"],
                    "situation":{"text":"The sampled opening establishes this scene's situation.","evidence_ids":[frames[0]["id"]]},
                    "action":{"text":"The sampled middle shows the scene's relevant action.","evidence_ids":[frames[len(frames)//2]["id"]]},
                    "consequence":{"text":"The sampled ending shows the scene's consequence.","evidence_ids":[frames[-1]["id"]]},
                    "useful_for_story":not omit_review,"completeness":"insufficient" if omit_review else "sufficient",
                    "uncertainty":"Controlled fixture; a semantic quality benchmark needs real footage."}
        if stage=="connections":
            return {"narrative":"factual_recap","bridges":[{"text":"The next selected scene develops this observed match thread.",
                        "evidence_ids":[f"a{i}",f"a{i+1}"]} for i in range(len(scenes)-1)]}
        raise AssertionError(f"Unexpected stage {stage}")
    return reply


class StoryFirstTests(unittest.TestCase):
    def make_plan(self):
        from test_match_story import fixture
        t,s,_=fixture()
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=scripted_editor(t,s)),patch("storyclip.story.frame"):
            plan=choose_story(t,s,Path(temp),video=Path("fixture"))
            t=json.loads((Path(temp)/"timeline.json").read_text())
        return plan,t,s

    def test_inspection_cannot_precede_story_outline(self):
        from test_match_story import fixture
        t,s,_=fixture();reply={"action":"inspect_scene","scene_id":"s2","reason":"Only inspect the finish"}
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",return_value=reply):
            with self.assertRaises(RuntimeError):choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertFalse((Path(temp)/"storyboard_v2.json").exists())

    def test_before_after_change_can_reuse_the_initial_observation(self):
        from test_match_story import fixture
        from storyclip.narrative import validate_outline
        t,s,_=fixture();outline=outline_for(s)
        outline["important_change"]["evidence_ids"]=["a0","a1"]
        self.assertEqual(validate_outline(outline,t,s).important_change.evidence_ids,["a0","a1"])

    def test_decisive_change_and_result_can_share_a_sampled_frame(self):
        from test_match_story import fixture
        from storyclip.narrative import validate_outline
        t,s,_=fixture();outline=outline_for(s)
        outline["important_change"]["evidence_ids"]=["a1","a2"]
        validate_outline(outline,t,s)
        outline["initial_situation"]["evidence_ids"]=["a2"]
        with self.assertRaises(ValueError):validate_outline(outline,t,s)

    def test_late_only_outline_is_rejected_before_frame_inspection(self):
        from test_match_story import fixture
        from storyclip.narrative import validate_outline
        t,s,_=fixture();s[0].update(start_s=60,end_s=65);s[1].update(start_s=70,end_s=75)
        with self.assertRaises(ValueError):validate_outline(outline_for(s),t,s)

    def test_outline_correction_names_missing_evidence_and_available_scene(self):
        from test_match_story import fixture
        from storyclip.narrative import validate_outline
        t,s,_=fixture();outline=outline_for(s)
        t["evidence"]["outside-anchor"]={**t["evidence"]["a0"],"id":"outside-anchor","time_s":25}
        t["evidence"]["later-anchor"]={**t["evidence"]["a1"],"id":"later-anchor","time_s":65}
        outline["initial_situation"]["evidence_ids"].append("outside-anchor")
        outline["important_change"]["evidence_ids"].append("later-anchor")
        s.append({"id":"unused-scene","start_s":20,"end_s":30})
        s.append({"id":"later-scene","start_s":60,"end_s":70})
        with self.assertRaisesRegex(ValueError,"outside-anchor at 25s.*unused-scene.*later-anchor at 65s.*later-scene.*ALL core citations"):
            validate_outline(outline,t,s)
        with self.assertRaisesRegex(ValueError,"Equivalent score observations INSIDE.*a0.*rewrite its timestamp"):
            validate_outline(outline,t,s)

    def test_compact_context_maps_evidence_to_selectable_scene_windows(self):
        from test_match_story import fixture
        from storyclip.planning import compact_context
        t,s,_=fixture();context=compact_context(t,s)
        self.assertEqual([o["available_scene_ids"] for o in context["observations"]],[["s0"],["s1"],["s2"]])
        self.assertEqual(context["scenes"][0]["context_start_s"],0)
        self.assertEqual(context["scenes"][0]["context_end_s"],10)

    def test_each_phase_has_its_own_correction_budget(self):
        from test_match_story import fixture
        t,s,_=fixture();editor=scripted_editor(t,s);seen=set()
        def intermittent(payload,*args,**kwargs):
            key=(payload["stage"],payload.get("scene_id"))
            if payload["stage"] in {"outline","scene","connections"} and key not in seen:
                seen.add(key);raise ValueError("Multiple JSON objects in the recorded response")
            return editor(payload,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=intermittent),patch("storyclip.story.frame"):
            plan=choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertEqual(plan["status"],"awaiting_human_review")
            trace=json.loads((Path(temp)/"story_v2_agent_trace.json").read_text())
            self.assertEqual(sum("validation_error" in e for e in trace),5)

    def test_failure_reports_the_phase_and_actual_validation_cause(self):
        from test_match_story import fixture
        t,s,_=fixture()
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=ValueError("Malformed response contains multiple objects")),patch("storyclip.story.frame") as frames:
            with self.assertRaisesRegex(RuntimeError,"outline after 3 replies.*multiple objects"):
                choose_story(t,s,Path(temp),video=Path("fixture"))
            frames.assert_not_called()
            state=json.loads((Path(temp)/"story_v2_run_state.json").read_text())
            self.assertEqual(state["requests"],3)

    def test_provider_retry_is_bounded_and_not_sent_as_model_correction(self):
        from test_match_story import fixture
        from storyclip.agent import PiRequestError
        for retryable in [True,False]:
            with self.subTest(retryable=retryable):
                t,s,_=fixture();editor=scripted_editor(t,s);calls=0
                def reply(payload,*args,**kwargs):
                    nonlocal calls
                    calls+=1
                    if calls==1:raise PiRequestError("Temporary provider failure" if retryable else "Quota exhausted",retryable=retryable)
                    if calls==2:self.assertNotIn("correction",payload)
                    return editor(payload,*args,**kwargs)
                with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
                    if retryable:
                        plan=choose_story(t,s,Path(temp),video=Path("fixture"))
                        self.assertEqual(plan["status"],"awaiting_human_review")
                    else:
                        with self.assertRaises(PiRequestError):choose_story(t,s,Path(temp),video=Path("fixture"))
                        self.assertEqual(calls,1)
                    trace=json.loads((Path(temp)/"story_v2_agent_trace.json").read_text())
                    self.assertEqual(sum("provider_error" in e for e in trace),1)

    def test_connection_recovery_waits_twice_and_stops_after_three_failures(self):
        from test_match_story import fixture
        from storyclip.agent import PiRequestError
        for failures in (2,3):
            with self.subTest(failures=failures):
                t,s,_=fixture();editor=scripted_editor(t,s);calls=0
                def reply(payload,*args,**kwargs):
                    nonlocal calls
                    calls+=1
                    if calls<=failures:raise PiRequestError("fetch failed")
                    self.assertNotIn("correction",payload)
                    return editor(payload,*args,**kwargs)
                with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"),patch("storyclip.planning.time.sleep") as sleep:
                    root=Path(temp)
                    if failures==2:
                        plan=choose_story(t,s,root,video=Path("fixture"))
                        self.assertEqual(plan["status"],"awaiting_human_review")
                    else:
                        with self.assertRaises(PiRequestError):choose_story(t,s,root,video=Path("fixture"))
                        self.assertEqual(calls,3)
                        self.assertFalse((root/"storyboard_v2.json").exists())
                        self.assertEqual(json.loads((root/"story_v2_run_state.json").read_text())["status"],"failed")
                    self.assertEqual([c.args[0] for c in sleep.call_args_list],[2,4])
                    trace=json.loads((root/"story_v2_agent_trace.json").read_text())
                    self.assertEqual(sum("provider_error" in e for e in trace),failures)

    def test_cut_correction_includes_offending_timestamp_and_previous_candidate(self):
        from test_match_story import fixture
        for boundary in ["start_s","end_s"]:
            with self.subTest(boundary=boundary):
                t,s,_=fixture();editor=scripted_editor(t,s);rejected=None
                def reply(payload,*args,**kwargs):
                    nonlocal rejected
                    correct=editor(payload,*args,**kwargs)
                    if payload["stage"]=="scene" and payload["scene_id"]=="s0":
                        self.assertEqual(payload["required_start_at_or_before_s"],3)
                        self.assertEqual(payload["required_end_after_s"],3)
                        if rejected is None:
                            rejected=copy.deepcopy(correct)
                            rejected[boundary]=5 if boundary=="start_s" else payload["inspection"]["frames"][-1]["time_s"]
                            return rejected
                        correction=payload["correction"]
                        self.assertEqual(correction["previous_candidate"],rejected)
                        self.assertIn("frame-s0-",correction["error"])
                        self.assertIn("outside cut [",correction["error"])
                        self.assertIn("end strictly after",correction["error"])
                    return correct
                with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
                    plan=choose_story(t,s,Path(temp),video=Path("fixture"))
                    self.assertEqual(plan["status"],"awaiting_human_review")

    def test_unfixable_scene_gets_one_bounded_story_revision(self):
        from test_match_story import fixture
        t,s,_=fixture();editor=scripted_editor(t,s);outlines=0;failed_replies=0
        def reply(payload,*args,**kwargs):
            nonlocal outlines,failed_replies
            if payload["stage"]=="outline":
                outlines+=1
                if outlines==2:
                    self.assertIn("s1",payload["feedback"]["issue"])
                    self.assertIn("scene_reviews",payload["feedback"])
            if payload["stage"]=="scene" and payload["scene_id"]=="s1" and outlines==1:
                failed_replies+=1;raise ValueError("No valid compact interval")
            return editor(payload,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
            plan=choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertEqual(plan["status"],"awaiting_human_review")
            self.assertEqual(outlines,2)
            self.assertEqual(failed_replies,3)

    def test_early_cuts_reserve_later_core_evidence_span(self):
        from test_match_story import fixture
        from storyclip.timeline import build_timeline
        t,_,_=fixture(duration=300)
        for observation,time in zip(t["observations"],[3,110,235]):observation["time_s"]=time
        ending={**t["observations"][-1],"id":"later-result","time_s":290}
        t=build_timeline(t["source"],{"manifest":{"source":t["source"],"start":0,"end":300},"events":[],"health":[]},t["observations"]+[ending])
        s=[{"id":f"s{i}","start_s":a,"end_s":b,"possible_role":role,"evidence_ids":[f"a{i}"]}
           for i,(a,b,role) in enumerate([(0,70,"setup"),(105,175,"development"),(230,300,"outcome")])]
        outline=outline_for(s);outline["resolution"]["evidence_ids"].append("later-result")
        editor=scripted_editor(t,s)
        def reply(payload,*args,**kwargs):
            if payload["stage"]=="outline":return outline
            result=editor(payload,*args,**kwargs)
            if payload["stage"]=="scene":
                start=235 if payload["scene_id"]=="s2" else payload["inspection"]["start_s"]
                end=start+min(60,payload["maximum_shot_s"])-.01
                frames=[f for f in payload["inspection"]["frames"] if start<=f["time_s"]<end]
                result.update(start_s=start,end_s=end)
                for key,frame in zip(["situation","action","consequence"],[frames[0],frames[len(frames)//2],frames[-1]]):
                    result[key]["evidence_ids"]=[frame["id"]]
                if payload["scene_id"]=="s1":
                    self.assertGreaterEqual(payload["reserved_for_remaining_scenes_s"],55.2)
                    self.assertLess(payload["maximum_shot_s"],60)
            return result
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
            plan=choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertLessEqual(plan["duration_s"],175)
            self.assertLessEqual(plan["beats"][-1]["start_s"],235)
            self.assertGreater(plan["beats"][-1]["end_s"],290)

    def test_impossible_core_span_is_rejected_before_inspection(self):
        from test_match_story import fixture
        t,s,_=fixture();outline=outline_for(s)
        t["source"]["duration"]=300;s[1].update(start_s=110,end_s=130);s[2].update(start_s=230,end_s=300)
        t["evidence"]["a1"]["time_s"]=120;t["evidence"]["a2"]["time_s"]=231
        t["evidence"]["wide-result"]={**t["evidence"]["a2"],"id":"wide-result","time_s":299}
        outline["resolution"]["evidence_ids"].append("wide-result")
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",return_value=outline),patch("storyclip.story.frame") as frames:
            with self.assertRaisesRegex(RuntimeError,"Minimum required scene lengths"):
                choose_story(t,s,Path(temp),video=Path("fixture"))
            frames.assert_not_called()

    def test_final_reservation_includes_known_gameplay_before_the_victory(self):
        from test_match_story import fixture
        t,s,_=fixture(duration=180)
        for i,time in enumerate([3,90,175]):
            t["evidence"][f"a{i}"]["time_s"]=time
        for scene,(start,end) in zip(s,[(0,50),(75,125),(135,180)]):scene.update(start_s=start,end_s=end)
        event={"id":"closing-pick","type":"player_kill","time_s":145,"status":"consistent_ocr","victim":"Sova"}
        t["events"]=[event];t["evidence"][event["id"]]=event
        editor=scripted_editor(t,s)
        def reply(payload,*args,**kwargs):
            if payload["stage"]=="scene" and payload["scene_id"]=="s1":
                self.assertGreaterEqual(payload["reserved_for_remaining_scenes_s"],30.2)
            if payload["stage"]=="scene" and payload["scene_id"]=="s2":
                self.assertAlmostEqual(payload["suggested_buildup_start_s"],145)
            return editor(payload,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
            choose_story(t,s,Path(temp),video=Path("fixture"))

    def test_generic_technical_story_is_not_approvable(self):
        from test_match_story import fixture
        t,s,r=fixture();p=validate_storyboard(r,t,s)
        with self.assertRaises(ValueError):approve_storyboard(p)

    def test_uninspected_middle_scene_cannot_pass_narrative_checks(self):
        p,t,s=self.make_plan();del p["scene_reviews"]["s1"]
        with self.assertRaises(ValueError):narrative_checks(p,t,s,p["scene_reviews"])

    def test_disconnected_beats_are_rejected(self):
        p,t,s=self.make_plan();p["beats"][0]["explanation"]["connection_to_next"]=None
        with self.assertRaises(ValueError):narrative_checks(p,t,s,p["scene_reviews"])

    def test_bridge_cannot_cite_an_unrelated_scene(self):
        p,t,s=self.make_plan();p["beats"][0]["explanation"]["connection_to_next"]["evidence_ids"]=["a2"]
        with self.assertRaises(ValueError):narrative_checks(p,t,s,p["scene_reviews"])

    def test_bridge_can_ground_itself_in_another_inspected_frame_inside_the_cut(self):
        from test_match_story import fixture
        t,s,_=fixture();editor=scripted_editor(t,s);extra=[]
        def reply(payload,*args,**kwargs):
            result=editor(payload,*args,**kwargs)
            if payload["stage"]=="connections":
                bridges=[]
                for pair in payload["adjacent_pairs"]:
                    ids=[]
                    for key,sid in [("from_evidence",pair["from_scene"]),("to_evidence",pair["to_scene"])]:
                        review=payload["scene_reviews"][sid]
                        cited={i for k in ["situation","action","consequence"] for i in review[k]["evidence_ids"]}
                        e=next(e for e in pair[key] if e["type"]=="source_frame" and e["id"] not in cited)
                        ids.append(e["id"]);extra.append((sid,e["id"]))
                    bridges.append({"text":"The reviewed context connects the next observed development.","evidence_ids":ids})
                result["bridges"]=bridges
            return result
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
            plan=choose_story(t,s,Path(temp),video=Path("fixture"))
            for sid,eid in extra:self.assertIn(eid,next(b for b in plan["beats"] if b["scene_id"]==sid)["evidence_ids"])

    def test_action_cannot_be_relabelled_without_visual_review(self):
        p,t,s=self.make_plan();p["beats"][1]["explanation"]["action"]["text"]="An unsupported ace changes the whole match."
        with self.assertRaises(ValueError):narrative_checks(p,t,s,p["scene_reviews"])

    def test_approval_is_invalidated_by_changes_to_cuts_or_explanations(self):
        for field in ["cut","explanation"]:
            p,t,s=self.make_plan();receipt=approve_storyboard(p);check_approval(p,receipt)
            if field=="cut":p["beats"][0]["end_s"]-=1
            else:p["outline"]["premise"]+=" Changed."
            with self.assertRaises(ValueError):check_approval(p,receipt)

    def test_failed_critique_cannot_be_approved(self):
        p,_,_=self.make_plan();p["story_review"]["scenes_connected"]=False
        with self.assertRaises(ValueError):approve_storyboard(p)

    def test_reviewer_can_reject_a_technically_valid_draft(self):
        from test_match_story import fixture
        t,s,_=fixture();critique=pass_review();critique.update(verdict="revise",scenes_connected=False,
            findings=[{"scene_id":"s1","issue":"Middle scene is unrelated to the premise.","remedy":"Choose a scene showing the important change."}])
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=scripted_editor(t,s,critic=critique)),patch("storyclip.story.frame"):
            with self.assertRaises(RuntimeError):choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertTrue((Path(temp)/"storyboard_draft.json").exists())
            self.assertFalse((Path(temp)/"storyboard_v2.json").exists())

    def test_same_source_feedback_survives_additional_samples_without_granting_approval(self):
        from storyclip.timeline import fingerprint
        p,t,s=self.make_plan();p["story_review"].update(verdict="revise",scenes_connected=False)
        old_identity=p["timeline_identity"]
        t["evidence"]["additional-frame"]={"id":"additional-frame","type":"source_frame","scene_id":"s0","time_s":15,"status":"sampled_frame","evidence_path":"fixture"}
        t["identity"]=fingerprint({k:v for k,v in t.items() if k!="identity"})
        self.assertNotEqual(old_identity,t["identity"])
        editor=scripted_editor(t,s);seen=False
        def reply(payload,*args,**kwargs):
            nonlocal seen
            if payload["stage"]=="outline":
                seen=True
                self.assertEqual(payload["feedback"]["previous_draft"]["timeline_identity"],old_identity)
                self.assertIn("Revalidate every claim",payload["feedback"]["instruction"])
            return editor(payload,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
            root=Path(temp);(root/"storyboard_draft.json").write_text(json.dumps(p))
            plan=choose_story(t,s,root,video=Path("fixture"))
            self.assertTrue(seen)
            self.assertEqual(plan["status"],"awaiting_human_review")
            self.assertFalse((root/"story_approval.json").exists())

    def test_critic_receives_in_cut_context_beyond_the_cited_frames(self):
        from test_match_story import fixture
        t,s,_=fixture();editor=scripted_editor(t,s);checked=False
        def reply(payload,*args,**kwargs):
            nonlocal checked
            if payload["stage"]=="critique":
                checked=True
                self.assertTrue(payload["render_contract"]["each_shot_is_one_continuous_source_interval"])
                self.assertTrue(payload["render_contract"]["images_are_sparse_samples_of_those_intervals"])
                cited={i for b in payload["storyboard"]["beats"] for i in b["evidence_ids"]}
                frames=[e for e in payload["evidence"].values() if e.get("type")=="source_frame"]
                self.assertTrue(any(e["id"] not in cited for e in frames))
                self.assertEqual(len(frames),len(payload["image_paths"]))
                for e in frames:
                    b=next(b for b in payload["storyboard"]["beats"] if b["scene_id"]==e["scene_id"])
                    self.assertLessEqual(b["start_s"],e["time_s"])
                    self.assertLess(e["time_s"],b["end_s"])
            return editor(payload,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
            choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertTrue(checked)

    def test_scene_recovery_does_not_consume_the_critique_revision(self):
        from test_match_story import fixture
        t,s,_=fixture();editor=scripted_editor(t,s);outlines=0;critiques=0
        def reply(payload,*args,**kwargs):
            nonlocal outlines,critiques
            result=editor(payload,*args,**kwargs)
            if payload["stage"]=="outline":outlines+=1
            if payload["stage"]=="scene" and payload["scene_id"]=="s1" and outlines==1:
                result.update(useful_for_story=False,completeness="insufficient")
            if payload["stage"]=="critique":
                critiques+=1
                if critiques==1:
                    result.update(verdict="revise",scenes_connected=False,findings=[{"scene_id":"s1","issue":"Middle scene lacks a clear connection.","remedy":"Choose a supported development."}])
            if payload["stage"]=="outline" and outlines==3:
                self.assertIn("previous_draft",payload["feedback"])
                self.assertEqual(payload["feedback"]["critique"]["verdict"],"revise")
            if payload["stage"] in {"scene","connections"} and outlines==3:
                self.assertEqual(payload["review_feedback"]["critique"]["verdict"],"revise")
                self.assertIn("previous_draft",payload["review_feedback"])
            return result
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=reply),patch("storyclip.story.frame"):
            plan=choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertEqual(plan["status"],"awaiting_human_review")
            self.assertEqual((outlines,critiques),(3,2))
            state=json.loads((Path(temp)/"story_v2_run_state.json").read_text())
            self.assertLessEqual(state["requests"],24)

    def test_renderer_requires_human_approval_before_ffmpeg(self):
        from storyclip.media import render_story
        p,t,s=self.make_plan()
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.media.probe",return_value=t["source"]),patch("storyclip.media.subprocess.run") as run:
            with self.assertRaises(ValueError):render_story(Path("fixture"),p,Path(temp)/"out.mp4",timeline=t,proposals=s)
            run.assert_not_called()

    def test_review_preview_rejects_unmarked_filename_or_failed_critique(self):
        from storyclip.media import render_story
        p,t,s=self.make_plan()
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.media.probe",return_value=t["source"]),patch("storyclip.media.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError,"draft filename"):
                render_story(Path("fixture"),p,Path(temp)/"out.mp4",timeline=t,proposals=s,review_preview=True)
            p["story_review"]["verdict"]="revise"
            with self.assertRaisesRegex(ValueError,"passes AI review"):
                render_story(Path("fixture"),p,Path(temp)/"review-draft.mp4",timeline=t,proposals=s,review_preview=True)
            run.assert_not_called()

    def test_story_first_backend_approval_does_not_depend_on_mode_label(self):
        from storyclip.media import render_story
        p,t,s=self.make_plan()
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.media.probe",return_value=t["source"]),patch("storyclip.media.subprocess.run") as run:
            for mode in ("match_story","kill_compilation_baseline"):
                with self.subTest(mode=mode):
                    p["mode"]=mode
                    with self.assertRaisesRegex(ValueError,"approve this exact storyboard"):
                        render_story(Path("fixture"),p,Path(temp)/"out.mp4",timeline=t,proposals=s)
            p["story_review"]["verdict"]="revise"
            with self.assertRaisesRegex(ValueError,"passes AI review"):
                render_story(Path("fixture"),p,Path(temp)/"review-draft.mp4",timeline=t,proposals=s,review_preview=True)
            run.assert_not_called()

    def test_comparison_matches_duration_with_four_available_encounters(self):
        from storyclip.story import compilation_baseline
        from test_match_story import fixture
        t,_,_=fixture();t["source"]["duration"]=400
        candidates=[]
        for i in range(4):
            eid=f"kill-{i}";t["evidence"][eid]={"id":eid,"type":"player_kill","time_s":90*i+12,"status":"consistent_ocr"}
            candidates.append({"start_s":90*i,"end_s":90*i+45,"event_ids":[eid]})
        with patch("storyclip.candidates.propose",return_value=candidates):
            plan,_=compilation_baseline(t,175)
        self.assertEqual(plan["duration_s"],175)

    def test_pi_defaults_are_luna(self):
        from storyclip.agent import choose
        self.assertEqual(choose.__kwdefaults__["model"],"gpt-6-luna")
        self.assertEqual(choose_story.__kwdefaults__["model"],"gpt-6-luna")


if __name__=="__main__":unittest.main()


class StoryReviewUITests(unittest.TestCase):
    def test_review_approval_export_gate_and_feedback_revocation(self):
        from streamlit.testing.v1 import AppTest
        from test_match_story import fixture
        t,s,_=fixture()
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=scripted_editor(t,s)),patch("storyclip.story.frame"):
            root=Path(temp)
            plan=choose_story(t,s,root,video=Path("fixture"))
            (root/"score_config.json").write_text('{}')
            source=f"""from pathlib import Path
import json
from storyclip.story_ui import show_story
root=Path({str(root)!r})
t=json.loads((root/'timeline.json').read_text())
show_story(root,Path('fixture'),t['source'],{{}},root)
"""
            app=AppTest.from_string(source).run()
            self.assertFalse(app.exception)
            export=next(b for b in app.button if b.label=='Export approved story')
            self.assertTrue(export.disabled)
            confirm=next(c for c in app.checkbox if 'I reviewed' in c.label)
            confirm.check().run()
            next(b for b in app.button if b.label=='Approve storyboard').click().run()
            self.assertFalse(app.exception)
            self.assertFalse(next(b for b in app.button if b.label=='Export approved story').disabled)
            receipt=json.loads((root/'story_approval.json').read_text());check_approval(plan,receipt)
            app.text_area[0].set_value('The middle scene does not show the change clearly.').run()
            next(b for b in app.button if b.label=='Save feedback for revision').click().run()
            receipt=json.loads((root/'story_approval.json').read_text())
            with self.assertRaises(ValueError):check_approval(plan,receipt)
            self.assertFalse(any(b.label=='Export approved story' for b in app.button))
