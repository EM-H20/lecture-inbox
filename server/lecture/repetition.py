"""Detect Whisper repetition loops. Ported from Chuseok22/transcribe-inbox (MIT)."""
from difflib import SequenceMatcher

from server.lecture.transcript import Segment

MIN_REPEAT_RUN = 3
SIMILARITY_THRESHOLD = 0.9
MIN_REPEAT_TEXT_LENGTH = 5  # short acknowledgements like "네" repeating are normal speech


def find_repetition_span(segments: list[Segment]) -> tuple[int, int] | None:
    """(first, last) indexes, inclusive, of the first run of 3+ near-identical consecutive segments."""
    run_start = 0
    for i in range(1, len(segments)):
        if SequenceMatcher(None, segments[i - 1].text, segments[i].text).ratio() < SIMILARITY_THRESHOLD:
            span = _qualifying(segments, run_start, i - 1)
            if span:
                return span
            run_start = i
    return _qualifying(segments, run_start, len(segments) - 1) if segments else None


def _qualifying(segments: list[Segment], start: int, end: int) -> tuple[int, int] | None:
    if end - start + 1 < MIN_REPEAT_RUN or len(segments[start].text) < MIN_REPEAT_TEXT_LENGTH:
        return None
    return (start, end)
