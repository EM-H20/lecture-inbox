import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.lecture.audio import extract_wav_span, normalize_to_wav, wav_duration_seconds
from server.lecture_testing import write_silent_wav


class WavTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.source = write_silent_wav(self.dir / "source.wav", 10)

    def tearDown(self):
        self.temp.cleanup()

    def span(self, start, end):
        dest = self.dir / "span.wav"
        offset = extract_wav_span(self.source, start, end, dest)
        return offset, wav_duration_seconds(dest)

    def test_duration(self):
        self.assertAlmostEqual(wav_duration_seconds(self.source), 10.0)

    def test_span_is_padded_half_a_second_each_side(self):
        self.assertEqual(self.span(2, 4), (1.5, 3.0))

    def test_span_is_clamped_to_the_end(self):
        self.assertEqual(self.span(8.5, 11), (8.0, 2.0))

    def test_span_past_the_end_is_empty(self):
        self.assertEqual(self.span(12, 13), (10.0, 0.0))

    def test_inverted_span_is_empty(self):
        self.assertEqual(self.span(5, 3), (4.5, 0.0))


class NormalizeTests(unittest.TestCase):
    def test_builds_audio_only_16k_mono_command(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, b"", b"")

        with patch("server.lecture.audio.shutil.which", return_value="/usr/bin/ffmpeg"):
            out = normalize_to_wav(Path("lec.mp4"), run=run)
        try:
            self.assertEqual(out.suffix, ".wav")
            self.assertTrue(out.exists())
            args = calls[0]
            self.assertEqual(args[0], "/usr/bin/ffmpeg")
            self.assertEqual(args[args.index("-i") + 1], "lec.mp4")
            for flag in ("-vn", "-ar", "16000", "-ac", "1"):
                self.assertIn(flag, args)
        finally:
            out.unlink(missing_ok=True)

    def test_failure_raises_and_removes_the_temp_file(self):
        seen = []

        def run(args, **kwargs):
            seen.append(Path(args[-1]))
            return subprocess.CompletedProcess(args, 1, b"", b"bad")

        with patch("server.lecture.audio.shutil.which", return_value="/usr/bin/ffmpeg"):
            with self.assertRaises(RuntimeError):
                normalize_to_wav(Path("x.mp4"), run=run)
        self.assertFalse(seen[0].exists())

    def test_missing_ffmpeg_explains_how_to_install(self):
        with patch("server.lecture.audio.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                normalize_to_wav(Path("x.mp4"))
        self.assertIn("brew install ffmpeg", str(caught.exception))
