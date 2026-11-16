import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from storyclip.media import probe, render_story
from storyclip.story import assisted_story, choose_story, propose_scenes, validate_storyboard
from storyclip.timeline import build_timeline, reconcile, validate_anchors
from storyclip.transcript import remap_captions, validate_transcript


def fixture(duration=90):
    source = {"duration":duration,"video":"fixture","width":1920,"height":1080,"has_audio":True}
    observations = [{"id":f"a{i}","type":"score","time_s":t,"score":score,"status":"reviewed_anchor",
                     "mapping_verified":True,"team_side":"left","evidence_path":"fixture","uncertainty":"reviewed"}
                    for i,(t,score) in enumerate([(3,[0,0]),(43,[6,7]),(83,[13,11])])]
    observations[-1]["outcome"] = "victory"
    scan = {"manifest":{"source":source,"start":0,"end":duration},"events":[],"health":[]}
    timeline = build_timeline(source,scan,observations)
    scenes = [{"id":f"s{i}","start_s":a,"end_s":b,"evidence_ids":[f"a{i}"],"possible_role":role,"uncertainty":"sampled"}
              for i,(a,b,role) in enumerate([(0,10,"setup"),(40,50,"development"),(80,90,"outcome")])]
    raw = {"narrative":"factual_recap","beats":[{"scene_id":s["id"],"role":s["possible_role"],"start_s":s["start_s"],"end_s":s["end_s"],"evidence_ids":s["evidence_ids"],"label":"outcome" if i==2 else "score","caption_evidence_id":s["evidence_ids"][0],"reason":"Observed context"} for i,s in enumerate(scenes)]}
    return timeline,scenes,raw


class StoryValidationTests(unittest.TestCase):
    def test_valid_story_has_source_output_map_and_generated_labels(self):
        t,s,r=fixture();p=validate_storyboard(r,t,s)
        self.assertEqual(p["duration_s"],30)
        self.assertEqual(p["beats"][1]["output_start_s"],10)
        self.assertEqual(p["beats"][1]["overlay"],"Trailing 6-7")
        self.assertEqual(p["beats"][-1]["overlay"],"Victory | 13-11")

    def test_context_labels_follow_the_observation_time(self):
        t,s,r=fixture();p=validate_storyboard(r,t,s)
        self.assertEqual(p["beats"][0]["overlay_start_s"],3)
        self.assertEqual(p["beats"][-1]["overlay_start_s"],23)
        self.assertEqual(p["beats"][-1]["overlay_end_s"],30)

    def test_sampled_score_caption_expires_instead_of_lingering_until_shot_end(self):
        t,s,r=fixture();p=validate_storyboard(r,t,s)
        self.assertLessEqual(p["beats"][0]["overlay_end_s"]-p["beats"][0]["overlay_start_s"],5)
        self.assertLess(p["beats"][0]["overlay_end_s"],p["beats"][0]["output_end_s"])

    def test_known_score_change_ends_caption_before_the_snapshot_expiry(self):
        t,s,r=fixture()
        t["observations"].append({**t["observations"][0],"id":"next-score","time_s":7,"score":[1,0]})
        p=validate_storyboard(r,t,s)
        self.assertEqual(p["beats"][0]["overlay_end_s"],7)

    def test_nonfinite_out_of_source_and_reversed_intervals_rejected(self):
        for a,b in [(float("nan"),10),(0,float("inf")),(-1,10),(10,0),(80,91)]:
            with self.subTest(a=a,b=b):
                t,s,r=fixture();r["beats"][0].update(start_s=a,end_s=b)
                with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_unknown_or_outside_evidence_rejected(self):
        for eid in ["invented","a2"]:
            t,s,r=fixture();r["beats"][0]["evidence_ids"]=[eid]
            with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_evidence_at_end_exclusive_rejected(self):
        t,s,r=fixture();r["beats"][0]["end_s"]=3
        with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_nonchronological_and_overlapping_scenes_rejected(self):
        t,s,r=fixture();r["beats"][0],r["beats"][1]=r["beats"][1],r["beats"][0]
        with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_budget_includes_all_shots(self):
        t,s,r=fixture()
        with self.assertRaises(ValueError):validate_storyboard(r,t,s,maximum=29)
        with self.assertRaises(ValueError):validate_storyboard(r,t,s,maximum=180)

    def test_mapping_required_for_team_outcome(self):
        t,s,r=fixture();t["evidence"]["a2"]["mapping_verified"]=False
        with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_unmapped_score_is_neutral(self):
        t,s,r=fixture();t["evidence"]["a1"]["mapping_verified"]=False
        self.assertEqual(validate_storyboard(r,t,s)["beats"][1]["overlay"],"HUD score 6-7")

    def test_unconfirmed_ocr_cannot_be_a_score_label(self):
        t,s,r=fixture();t["evidence"]["a1"]["status"]="needs_review"
        with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_comeback_requires_cited_mapped_deficit_and_recovery(self):
        t,s,r=fixture();r["narrative"]="comeback"
        self.assertEqual(validate_storyboard(r,t,s)["narrative"],"comeback")
        t["evidence"]["a1"]["mapping_verified"]=False
        with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_final_result_cannot_be_dropped(self):
        t,s,r=fixture();r["beats"][-1].update(evidence_ids=["a1"],label="phase",caption_evidence_id=None)
        with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_speech_captions_remap_into_assembled_time(self):
        t,s,r=fixture();speech=validate_transcript([{"start_s":41,"end_s":44,"text":"Actual speech"}],90)
        t["transcript"]=speech;t["evidence"].update({x["id"]:x for x in speech});r["beats"][1]["transcript_ids"]=[speech[0]["id"]]
        p=validate_storyboard(r,t,s);captions=remap_captions(p["beats"],speech)
        self.assertEqual((captions[0]["start_s"],captions[0]["end_s"]),(11,14))
        r["beats"][1]["end_s"]=43
        with self.assertRaises(ValueError):validate_storyboard(r,t,s)

    def test_transcript_window_offsets_and_invalid_bounds(self):
        rows=validate_transcript([{"start_s":1,"end_s":2,"text":"hello"}],90,offset=40)
        self.assertEqual(rows[0]["start_s"],41)
        with self.assertRaises(ValueError):validate_transcript([{"start_s":1,"end_s":2,"text":"hello"}],1)

    def test_quiet_and_unknown_intervals_remain_in_timeline(self):
        t,_,_=fixture();self.assertEqual(t["intervals"][0]["start_s"],0)
        self.assertEqual(t["intervals"][-1]["end_s"],90)
        self.assertTrue(any(r["kind"]=="unresolved_interval" for r in t["intervals"]))

    def test_partial_discovery_is_rejected(self):
        t,_,_=fixture();scan={"manifest":{"source":t["source"],"start":10,"end":90},"events":[],"health":[]}
        with self.assertRaises(ValueError):build_timeline(t["source"],scan,[])

    def test_ocr_regression_and_isolated_reading_need_review(self):
        rows=[{"id":str(i),"time_s":i*30,"score":v,"status":"unconfirmed_ocr"} for i,v in enumerate([[2,2],[2,2],[1,2],[1,2],[10,8]])]
        result=reconcile(rows)
        self.assertEqual(result[1]["status"],"consistent_ocr")
        self.assertEqual(result[2]["status"],"needs_review")
        self.assertEqual(result[-1]["status"],"needs_review")

    def test_source_bound_anchor_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            image=Path(temp)/"frame.png";image.write_bytes(b"fixture")
            source={"duration":90};data={"source":source,"observations":[{"time_s":3,"score":[0,0],"review_note":"inspected","evidence_path":str(image),"team_side":"left"}]}
            self.assertTrue(validate_anchors(data,source)[0]["mapping_verified"])
            with self.assertRaises(ValueError):validate_anchors(data,{"duration":91})

    def test_proposals_preserve_all_three_phases_without_kills(self):
        t,_,_=fixture();scenes=propose_scenes(t)
        self.assertEqual({s["phase"] for s in scenes},{"early","middle","late"})
        self.assertTrue(any("a2" in s["evidence_ids"] for s in scenes))

    def test_story_agent_inspects_every_scene_and_logs_grounded_submission(self):
        from test_story_first import scripted_editor
        t,s,r=fixture()
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=scripted_editor(t,s)),patch("storyclip.story.frame"):
            plan=choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertEqual(plan["model"],"gpt-6-luna")
            self.assertEqual(plan["planning_version"],2)
            self.assertEqual(set(plan["scene_reviews"]),{"s0","s1","s2"})
            self.assertTrue((Path(temp)/"STORY_REVIEW.md").exists())
            self.assertFalse((Path(temp)/"match_story_v2.mp4").exists())

    def test_agent_dense_rescan_updates_timeline_and_preserves_source_offsets(self):
        from test_story_first import scripted_editor
        t,s,r=fixture()
        scan={"manifest":{"source":t["source"],"start":0,"end":90},"events":[],"health":[]}
        dense={"events":[{"id":"kill-0001","time_s":42,"victim":"Sova","killer":"Me","type":"player_kill","status":"consistent_ocr"}],"health":[]}
        editor=scripted_editor(t,s)
        refined=False
        def respond(payload,model,cache_dir,**kwargs):
            nonlocal refined
            reply=editor(payload,model,cache_dir,**kwargs)
            if payload["stage"]=="scene" and payload["scene_id"]=="s1" and not refined:
                refined=True;reply.update(useful_for_story=False,completeness="insufficient")
            return reply
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",side_effect=respond),patch("storyclip.story.frame"),patch("storyclip.story.score_pass",return_value=[]),patch("storyclip.detectors.scan",return_value=dense):
            plan=choose_story(t,s,Path(temp),video=Path("fixture"),scan=scan,score_config={},hud_config={})
            timeline=json.loads((Path(temp)/"timeline.json").read_text())
            self.assertEqual(timeline["events"][0]["time_s"],42)
            self.assertTrue(timeline["events"][0]["id"].startswith("rescan-40000-"))
            self.assertEqual(plan["timeline_identity"],timeline["identity"])

    def test_anchor_outcome_cannot_contradict_the_mapped_score(self):
        with tempfile.TemporaryDirectory() as temp:
            image=Path(temp)/"frame.png";image.write_bytes(b"fixture")
            source={"duration":90};data={"source":source,"observations":[{"time_s":83,"score":[11,13],"team_side":"left","outcome":"victory","review_note":"reviewed","evidence_path":str(image)}]}
            with self.assertRaises(ValueError):validate_anchors(data,source)

    def test_agent_correction_does_not_publish_uninspected_story(self):
        t,s,r=fixture();reply={"action":"submit_storyboard","storyboard":r,"reason":"skip tools"}
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.story.invoke_pi",return_value=reply):
            with self.assertRaises(RuntimeError):choose_story(t,s,Path(temp),video=Path("fixture"))
            self.assertFalse((Path(temp)/"storyboard.json").exists())

    def test_renderer_rejects_changed_source_before_publishing(self):
        t,s,r=fixture();p=validate_storyboard(r,t,s)
        with tempfile.TemporaryDirectory() as temp,patch("storyclip.media.probe",return_value={"duration":91}):
            with self.assertRaises(ValueError):render_story(Path("fixture"),p,Path(temp)/"out.mp4",timeline=t,proposals=s)
            self.assertFalse((Path(temp)/"out.mp4").exists())


class RenderIntegrationTests(unittest.TestCase):
    def test_real_multishot_render_preserves_cut_order_audio_and_caption_mapping(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);video=root/"source.mp4"
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=red:s=160x90:r=30:d=3",
                            "-f","lavfi","-i","color=green:s=160x90:r=30:d=3","-f","lavfi","-i","color=blue:s=160x90:r=30:d=3",
                            "-f","lavfi","-i","aevalsrc=0.15*sin(2*PI*(if(lt(t\,3)\,440\,if(lt(t\,6)\,660\,880)))*t):s=48000:d=9",
                            "-filter_complex","[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]","-map","[v]","-map","3:a",
                            "-c:v","libx264","-c:a","aac","-y",str(video)],check=True)
            source=probe(video);observations=[]
            for i,timestamp in enumerate([1,4,7]):
                observations.append({"id":f"a{i}","type":"score","time_s":timestamp,"score":[i,i],"status":"reviewed_anchor","mapping_verified":False})
            scan={"manifest":{"source":source,"start":0,"end":source["duration"]},"events":[],"health":[]}
            speech=validate_transcript([{"start_s":4.2,"end_s":4.7,"text":"caption with : apostrophe ' and 100%"}],source["duration"])
            timeline=build_timeline(source,scan,observations,transcript=speech)
            scenes=[{"id":f"s{i}","start_s":a,"end_s":b} for i,(a,b) in enumerate([(0,2),(3,5),(6,8)])]
            raw={"narrative":"factual_recap","beats":[{"scene_id":s["id"],"role":["setup","development","outcome"][i],"start_s":s["start_s"],"end_s":s["end_s"],"evidence_ids":[f"a{i}"],"reason":"test"} for i,s in enumerate(scenes)]}
            raw["beats"][1]["transcript_ids"]=[speech[0]["id"]]
            plan=validate_storyboard(raw,timeline,scenes);output=root/"story.mp4"
            result=render_story(video,plan,output,timeline=timeline,proposals=scenes)
            self.assertAlmostEqual(result["output"]["duration"],6,delta=.1)
            self.assertTrue(result["output"]["has_audio"])
            mapping=json.loads(output.with_suffix(".mapping.json").read_text())
            self.assertAlmostEqual(mapping["captions"][0]["start_s"],3.2)
            capture=cv2.VideoCapture(str(output))
            for timestamp,channel in [(1,2),(3,1),(5,0)]:
                capture.set(cv2.CAP_PROP_POS_MSEC,timestamp*1000);ok,im=capture.read();self.assertTrue(ok)
                self.assertEqual(int(np.argmax(im[640,360])),channel)
            capture.release()
            # Exercise the story-first approval and visible-bridge path with the same real media.
            from storyclip.narrative import approve_storyboard
            from test_story_first import scripted_editor
            for i,o in enumerate(observations):
                o.update(score=[[0,0],[6,7],[13,11]][i],mapping_verified=True,team_side="left")
            observations[-1]["outcome"]="victory"
            narrative_timeline=build_timeline(source,scan,observations)
            narrative_scenes=[{**s,"possible_role":["setup","development","outcome"][i]} for i,s in enumerate(scenes)]
            with patch("storyclip.story.invoke_pi",side_effect=scripted_editor(narrative_timeline,narrative_scenes)):
                draft=choose_story(narrative_timeline,narrative_scenes,root,video=video)
            narrative_timeline=json.loads((root/"timeline.json").read_text())
            receipt=approve_storyboard(draft)
            approved_output=root/"approved.mp4"
            approved_metrics=render_story(video,draft,approved_output,timeline=narrative_timeline,proposals=narrative_scenes,approval=receipt)
            self.assertEqual(approved_metrics["shot_count"],3)
            self.assertAlmostEqual(approved_metrics["output"]["duration"],6,delta=.1)
            approved_map=json.loads(approved_output.with_suffix(".mapping.json").read_text())
            self.assertTrue(approved_map["shots"][0]["explanation"]["connection_to_next"])
            self.assertEqual(approved_map["storyboard_hash"],receipt["storyboard_hash"])
            preview_output=root/"review-draft.mp4"
            preview_metrics=render_story(video,draft,preview_output,timeline=narrative_timeline,proposals=narrative_scenes,review_preview=True)
            self.assertTrue(preview_metrics["review_preview"])
            self.assertTrue(preview_metrics["output"]["has_audio"])
            self.assertAlmostEqual(preview_metrics["output"]["duration"],6,delta=.1)
            preview_map=json.loads(preview_output.with_suffix(".mapping.json").read_text())
            self.assertTrue(preview_map["review_preview"])
            capture=cv2.VideoCapture(str(preview_output))
            capture.set(cv2.CAP_PROP_POS_MSEC,1000);ok,im=capture.read();self.assertTrue(ok)
            capture.release()
            watermark=im[1140:1185,36:520]
            amber=(watermark[:,:,2]>180)&(watermark[:,:,1]>140)&(watermark[:,:,0]<150)
            self.assertGreater(int(amber.sum()),100)
            pcm=subprocess.run(["ffmpeg","-v","error","-i",str(output),"-vn","-f","f32le","-ac","1","-ar","48000","pipe:1"],capture_output=True,check=True).stdout
            samples=np.frombuffer(pcm,np.float32)
            self.assertGreater(np.sqrt(np.mean(samples*samples)),.02)
            for second,frequency in [(1,440),(3,660),(5,880)]:
                chunk=samples[second*48000:(second+1)*48000]
                peak=np.argmax(abs(np.fft.rfft(chunk)))
                self.assertAlmostEqual(peak,frequency,delta=2)


if __name__=="__main__":unittest.main()
