import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from server.lecture.transcript import Segment
from server.lecture.whisper import CANCELLED, REPETITION_PLACEHOLDER, VAD_MODEL_FILE, WhisperCli
from server.lecture_testing import write_silent_wav

LOOP = "같은 문장을 계속 반복합니다"


def raw(*entries):
    """entries are (from_ms, to_ms, text), shaped like whisper-cli -oj output."""
    return {"result": {"language": "ko"},
            "transcription": [{"offsets": {"from": a, "to": b}, "text": t} for a, b, t in entries]}


def looping(start_ms=0, count=4, step_ms=2000):
    return raw(*[(start_ms + i * step_ms, start_ms + (i + 1) * step_ms, " " + LOOP) for i in range(count)])


class FakeProcess:
    """Stands in for a Popen whisper-cli: writes its canned JSON when communicate() is called."""
    def __init__(self, args, output):
        self.args, self.output, self.returncode = args, output, None

    def communicate(self):
        if self.output is None:
            self.returncode = 1
            return None, b"boom"
        Path(self.args[self.args.index("-of") + 1] + ".json").write_text(json.dumps(self.output), encoding="utf-8")
        self.returncode = 0
        return None, b""

    def terminate(self):
        pass


class FakeRun:
    """A Popen factory: each launch consumes the next canned output. None = non-zero exit."""
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        return FakeProcess(args, self.outputs.pop(0))


class BlockingProcess:
    """A whisper-cli that never finishes until terminate() is called."""
    def __init__(self):
        self.started, self.released = threading.Event(), threading.Event()
        self.returncode = None

    def communicate(self):
        self.started.set()
        self.released.wait(5)
        self.returncode = -15
        return None, b""

    def terminate(self):
        self.released.set()


class WhisperCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wav = write_silent_wav(Path(self.temp.name) / "a.wav", 12)

    def tearDown(self):
        self.temp.cleanup()

    def engine(self, *outputs):
        self.run = FakeRun(*outputs)
        return WhisperCli("whisper-cli", "models/ggml-small.bin", "models/vad.bin", popen=self.run)

    def test_transcribes_with_vad_and_no_context(self):
        result = self.engine(raw((0, 2400, " 안녕하세요"), (2400, 3000, "  "), (3000, 5000, " 두 번째"))) \
            .transcribe(self.wav, "a.mp4")
        self.assertEqual(result.segments, [Segment(0.0, 2.4, "안녕하세요"), Segment(3.0, 5.0, "두 번째")])
        self.assertEqual((result.model, result.language, result.source_filename), ("ggml-small", "ko", "a.mp4"))
        self.assertAlmostEqual(result.duration_seconds, 12.0)
        args = self.run.calls[0]
        self.assertIn("--vad", args)
        self.assertIn("-oj", args)
        self.assertEqual(args[args.index("-mc") + 1], "0")
        self.assertEqual(args[args.index("-l") + 1], "ko")
        self.assertEqual(args[args.index("-f") + 1], str(self.wav))

    def test_loop_is_redecoded_and_replaced_with_absolute_times(self):
        first = raw((0, 2000, " 안녕하세요 시작합니다"), *[(2000 + i * 2000, 4000 + i * 2000, " " + LOOP) for i in range(4)])
        retry = raw((500, 1500, " 정상 문장입니다"))  # decoded from a clip that starts at 1.5 s
        result = self.engine(first, retry).transcribe(self.wav, "a.mp4")
        self.assertEqual(result.segments, [Segment(0.0, 2.0, "안녕하세요 시작합니다"), Segment(2.0, 3.0, "정상 문장입니다")])
        self.assertEqual(len(self.run.calls), 2)

    def test_unresolved_loop_becomes_a_marked_placeholder(self):
        result = self.engine(looping(), looping(), looping()).transcribe(self.wav, "a.mp4")
        self.assertEqual(result.segments, [Segment(0.0, 8.0, REPETITION_PLACEHOLDER + LOOP)])
        self.assertEqual(len(self.run.calls), 3)

    def test_failed_retry_decode_falls_back_to_the_placeholder(self):
        result = self.engine(looping(), None, None).transcribe(self.wav, "a.mp4")
        self.assertEqual(result.segments, [Segment(0.0, 8.0, REPETITION_PLACEHOLDER + LOOP)])

    def test_overlong_loop_is_not_retried(self):
        first = raw(*[(i * 60000, (i + 1) * 60000, " " + LOOP) for i in range(4)])
        result = self.engine(first).transcribe(self.wav, "a.mp4")
        self.assertEqual(len(self.run.calls), 1)
        self.assertEqual(result.segments, [Segment(0.0, 240.0, REPETITION_PLACEHOLDER + LOOP)])

    def test_nonzero_exit_raises(self):
        with self.assertRaises(RuntimeError):
            self.engine(None).transcribe(self.wav, "a.mp4")

    def test_invalid_utf8_in_json_is_replaced_not_fatal(self):
        class BytesProcess:
            returncode = 0

            def __init__(self, args):
                self.args = args

            def communicate(self):
                body = b'{"transcription":[{"offsets":{"from":0,"to":1000},"text":" \xed\x95"}]}'
                Path(self.args[self.args.index("-of") + 1] + ".json").write_bytes(body)
                return None, b""

            def terminate(self):
                pass

        result = WhisperCli("w", "m.bin", "v.bin", popen=lambda args, **kwargs: BytesProcess(args)) \
            .transcribe(self.wav, "a.mp4")
        self.assertIn("�", result.segments[0].text)

    def test_stop_terminates_a_running_whisper_and_raises(self):
        process = BlockingProcess()
        engine = WhisperCli("w", "m.bin", "v.bin", popen=lambda args, **kwargs: process)
        outcome = []

        def work():
            try:
                engine.transcribe(self.wav, "a.mp4")
            except RuntimeError as error:
                outcome.append(str(error))

        thread = threading.Thread(target=work)
        thread.start()
        self.assertTrue(process.started.wait(5))
        engine.stop()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [CANCELLED])

    def test_stop_during_a_repetition_retry_ends_the_transcription(self):
        outputs = [looping(), looping(), looping()]
        calls = []

        def popen(args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                engine.stop()  # the user cancels just as the retry is being launched
            return FakeProcess(args, outputs.pop(0))

        engine = WhisperCli("w", "m.bin", "v.bin", popen=popen)
        with self.assertRaises(RuntimeError) as caught:
            engine.transcribe(self.wav, "a.mp4")
        self.assertEqual(str(caught.exception), CANCELLED)
        self.assertEqual(len(calls), 2)  # no further retry was launched after the cancel

    def test_stop_before_start_never_launches_whisper(self):
        launched = []
        engine = WhisperCli("w", "m.bin", "v.bin", popen=lambda args, **kwargs: launched.append(args))
        engine.stop()
        with self.assertRaises(RuntimeError) as caught:
            engine.transcribe(self.wav, "a.mp4")
        self.assertEqual(str(caught.exception), CANCELLED)
        self.assertEqual(launched, [])


class FromEnvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "models").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def models(self, *names):
        for name in names:
            (self.root / "models" / name).write_bytes(b"x")

    def load(self, which="/opt/homebrew/bin/whisper-cli", **env):
        env = {"WHISPER_CLI_BINARY": "", **env}
        with patch.dict(os.environ, env), patch("server.lecture.whisper.shutil.which", return_value=which):
            if "WHISPER_MODEL" not in env:
                os.environ.pop("WHISPER_MODEL", None)  # exercise the real default
            return WhisperCli.from_env(self.root)

    def test_defaults_to_the_largest_model(self):
        self.models("ggml-large-v3.bin", VAD_MODEL_FILE)
        engine = self.load()
        self.assertEqual(engine.binary, "/opt/homebrew/bin/whisper-cli")
        self.assertEqual(engine.model_path, str(self.root / "models" / "ggml-large-v3.bin"))
        self.assertEqual(engine.vad_model_path, str(self.root / "models" / VAD_MODEL_FILE))

    def test_model_size_comes_from_the_environment(self):
        self.models("ggml-small.bin", VAD_MODEL_FILE)
        self.assertTrue(self.load(WHISPER_MODEL="small").model_path.endswith("ggml-small.bin"))

    def test_unknown_model_size_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.load(WHISPER_MODEL="../x")

    def test_missing_binary_explains_how_to_install(self):
        with self.assertRaises(RuntimeError) as caught:
            self.load(which=None)
        self.assertIn("brew install whisper-cpp", str(caught.exception))

    def test_missing_model_file_points_to_the_download_command(self):
        with self.assertRaises(RuntimeError) as caught:
            self.load()
        self.assertIn("lecture -- models", str(caught.exception))
