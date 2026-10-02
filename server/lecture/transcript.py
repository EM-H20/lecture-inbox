"""Transcript model and the two text formats. The .md timestamps are what note-taking agents copy.

The timestamp formatting follows Chuseok22/transcribe-inbox's transcript formatters (MIT).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    model: str
    language: str
    source_filename: str
    duration_seconds: float
    segments: list[Segment]


def format_hms(seconds: float) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def to_markdown(transcript: Transcript) -> str:
    return "".join(f"[{format_hms(s.start)}] {s.text}\n" for s in transcript.segments)


def to_plain_text(transcript: Transcript) -> str:
    return "".join(f"{s.text}\n" for s in transcript.segments)
