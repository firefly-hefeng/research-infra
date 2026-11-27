import copy
import contextlib
import hashlib
import io
import json
import math
import struct
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import research_experiment as ex
from tools import research_experiment_audio as audio
from tools import run_research_experiment as cli


def wav(amplitudes, rate=8000):
    target = io.BytesIO()
    with wave.open(target, "wb") as w:
        w.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        for value in amplitudes:
            w.writeframes(struct.pack("<h", value) * (rate // 50))
    return target.getvalue()


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.sources = {
            "directions": {"items": [{"id": "universal-voice-encoder", "title": "通用疾病声音 Encoder", "question": "声音表征"},
                                     {"id": "separate", "title": "情绪方向"}]},
            "library": {"items": [{"id": audio.RECORD, "kind": "dataset", "title": "MDVR-KCL", "summary": "疾病声音"}]},
            "research": {"research_tracks": [{"id": "universal-voice-encoder", "name": "编码器", "validation": "研究路线"}]},
            "papers": {"papers": [{"id": "a", "bibliography": {"title": "Voice representation for speech", "doi": "10.0/a"}},
                                 {"id": "b", "bibliography": {"title": "Across devices", "tags": ["语音表征"]}},
                                 {"id": "c", "filename": "Voice representation.pdf"},
                                 {"id": "d", "card": {"title": "Device-only baselines"}}]},
        }

    def test_direction_plan_uses_archive_identity_and_reproducible_retrieval(self):
        plan = ex.build_plan("universal-voice-encoder", self.sources)
        self.assertEqual([p["id"] for p in plan["protocols"]], [ex.AUDIO, ex.SEARCH])
        self.assertEqual(plan["context"]["archive"][0]["validation"], "研究路线")
        with patch.object(audio, "ARCHIVE", "missing"):
            result = ex.execute_plan(plan, self.sources)
            self.assertEqual(result["fingerprint"], ex.execute_plan(plan, self.sources)["fingerprint"])
        self.assertEqual(result["status"], "partial")
        literature = result["results"][1]
        self.assertEqual((literature["metrics"]["title_matches"], literature["metrics"]["incremental_matches"],
                          literature["metrics"]["expanded_doi_pct"]), (1, 1, 50))
        self.assertEqual([r["id"] for r in literature["matched_records"]], ["a", "b"])

    def test_unregistered_zero_unknown_and_known_negative_results(self):
        self.assertEqual(ex.build_plan("星系弱透镜", self.sources)["status"], "no_protocol")
        custom = ex.build_plan("语音表征", self.sources)
        self.assertFalse(custom["registered_direction"])
        self.assertEqual([p["id"] for p in custom["protocols"]], [ex.SEARCH])
        plan = ex.build_plan("separate", self.sources)
        metrics = ex.execute_plan(plan, self.sources)["results"][0]["metrics"]
        self.assertEqual(metrics["expanded_matches"], 0)
        self.assertIsNone(metrics["expanded_doi_pct"])
        del self.sources["papers"]
        self.assertEqual(ex.build_plan("separate", self.sources)["status"], "no_protocol")

    def test_stale_and_unapproved_execution_parameters(self):
        plan = ex.build_plan("separate", self.sources)
        tampered = copy.deepcopy(plan)
        tampered["protocols"][0]["parameters"]["path"] = "elsewhere"
        with self.assertRaises(ValueError):
            ex.execute_plan(tampered, self.sources)
        self.sources["papers"]["papers"][0]["bibliography"]["title"] = "changed"
        with self.assertRaises(ValueError):
            ex.execute_plan(plan, self.sources)
        self.sources["papers"]["papers"].append(self.sources["papers"]["papers"][0])
        with self.assertRaisesRegex(ValueError, "重复"):
            ex.build_plan("separate", self.sources)

    def test_asset_version_and_source_match(self):
        self.sources["library"]["items"][0]["title"] = "another dataset"
        self.assertNotIn(ex.AUDIO, [p["id"] for p in ex.build_plan("MDVR-KCL", self.sources)["protocols"]])

    def test_complete_paired_analysis_and_exclusions(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
            # 0, ~-44 dBFS and ~-24 dBFS. Three 20 ms frames in the first recording.
            archive.writestr("group/a.wav", wav([0, 200, 2000]))
            archive.writestr("group/b.wav", wav([2000, 2000]))
            archive.writestr("broken.wav", b"not a wave")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio.zip"
            path.write_bytes(data.getvalue())
            with patch.object(audio, "ARCHIVE", str(path)), patch.object(audio, "SIZE", path.stat().st_size), \
                    patch.object(audio, "SHA256", hashlib.sha256(data.getvalue()).hexdigest()), \
                    patch.dict(audio.PARAMETERS, expected_wav_files=3), patch.object(audio, "_verified", {}):
                m = audio.analyze()
                self.assertEqual(m["status"], "partial")
                metrics = m["metrics"]
                self.assertEqual(metrics["frames"], 5)
                self.assertEqual(metrics["retained_frame_pct"], {"-50": 80.0, "-40": 60.0})
                self.assertEqual(metrics["paired_median_loss_pp"], 16.667)
                self.assertEqual(metrics["changed_recordings"], 1)
                self.assertEqual(metrics["crop_retained_duration_pct"], {"10": 100.0, "30": 100.0})
                self.assertEqual(metrics["analyzed_recordings"], 2)
                self.assertNotIn("group/a.wav", str(m))
                changed = bytearray(data.getvalue())
                changed[20] ^= 1
                path.write_bytes(changed)
                with patch.object(audio, "_verified", {}):
                    self.assertEqual(audio.analyze()["status"], "unavailable")

    def test_encodings_stereo_power_and_nonfinite_float(self):
        for bits, raw in [(8, bytes([192, 64])), (16, struct.pack("<hh", 16384, -16384)),
                          (24, bytes.fromhex("0000400000c0")), (32, struct.pack("<ii", 1 << 30, -(1 << 30)))]:
            powers = audio.frame_powers(1, 2, 1000, bits, raw * 20)
            self.assertEqual(powers, [0.25])
        self.assertEqual(audio.frame_powers(3, 2, 1000, 32, struct.pack("<ff", .5, -.5) * 20), [0.25])
        with self.assertRaisesRegex(ValueError, "非有限"):
            audio.frame_powers(3, 1, 1000, 32, struct.pack("<f", math.nan) * 20)

    def test_speaker_split_construction_and_member_only_execution(self):
        files = [f"Actor_{a:02}/03-01-{e:02}-{i:02}-{s:02}-{t:02}-{a:02}.wav"
                 for a in range(1, 25) for e in range(1, 9) for i in ([1] if e == 1 else [1, 2])
                 for s in [1, 2] for t in [1, 2]]
        m = audio.speaker_splits(files)
        self.assertEqual(m["recording"]["seen_actor_pct"], 100)
        self.assertEqual(m["speaker"]["seen_actor_pct"], 0)
        self.assertEqual(m["speaker"]["max_emotion_share_deviation_pp"], 0)
        self.assertEqual(m["speaker"]["fold_sizes"], [240] * 6)
        self.assertEqual(m, audio.speaker_splits(files[::-1]))
        with self.assertRaises(ValueError):
            audio.speaker_splits(files[:-1])
        self.sources["library"]["items"].append({"id": audio.RAV_SOURCE["id"], "title": "RAVDESS Speech", "kind": "dataset"})
        self.assertNotIn(ex.SPEAKER, [p["id"] for p in ex.build_plan("语音情绪", self.sources)["protocols"]])
        restricted = ex.build_plan("语音情绪", self.sources, allow_noncommercial=True)
        self.assertIn(ex.SPEAKER, [p["id"] for p in restricted["protocols"]])
        with self.assertRaises(ValueError):
            ex.execute_plan(restricted, self.sources)

    def test_cli_publishes_negative_result_once_from_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            source, result = (Path(directory) / n for n in ("context.json", "run.json"))
            source.write_text(json.dumps({"schema_version": "1.0", "mode": "offline_snapshot",
                    "sources": {"papers": {"url": "/papers/api/catalog", "status": "ok", "data": self.sources["papers"]}}}), encoding="utf8")
            args = ["星系弱透镜", "--snapshot", str(source), "--output", str(result)]
            self.assertEqual(cli.main(args), 2)
            first = result.read_bytes()
            self.assertEqual(json.loads(first)["run"]["status"], "unavailable")
            self.assertEqual(cli.main(args), 1)
            self.assertEqual(result.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
