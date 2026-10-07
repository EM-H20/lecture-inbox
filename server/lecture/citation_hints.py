"""Literal transcript checks for the required terminology-correction table.

These are navigation hints, not semantic grades: a paraphrase can fail an exact
match, and the presence of a string does not establish the claim around it.
"""
import re
import unicodedata


STAMP = r"\d{2}:[0-5]\d:[0-5]\d"
CITATION = re.compile(rf"\[({STAMP})\](?:\s*[-–—~∼]\s*\[({STAMP})\])?")


def literal(text):
    return re.sub(r"[\s'\"“”‘’`*]", "", unicodedata.normalize("NFC", text))


def transcript_quote_hints(text, transcript):
    starts = list(re.finditer(rf"^\s*\[({STAMP})\]", transcript, re.MULTILINE))
    passages = {}
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(transcript)
        passages.setdefault(start[1], []).append(transcript[start.end():end])
    passages = {stamp: literal(" ".join(parts)) for stamp, parts in passages.items()}
    hints, table, fenced = [], False, False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced, table = not fenced, False
            continue
        if fenced:
            continue
        if not line.strip().startswith("|"):
            table = False
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if [literal(cell) for cell in cells] == ["본문표기", "전사표현", "근거"]:
            table = True
            continue
        if not table or len(cells) != 3 or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        cited = set()
        for match in CITATION.finditer(cells[2]):
            start, end = match[1], match[2]
            if end is None and start in passages:
                cited.add(start)
            elif start in passages and end in passages and start <= end:
                cited.update(stamp for stamp in passages if start <= stamp <= end)
        supported = "".join(passages[stamp] for stamp in sorted(cited))
        for expression in dict.fromkeys(re.split(r"[,·、/;]", cells[1])):
            quote = literal(expression)
            if not quote or quote in {"-", "—", "–"} or quote in supported:
                continue
            hints.append(dict(note_line=number, transcript_expression=expression.strip(),
                              cited_timestamps=sorted(cited),
                              matching_timestamps=[stamp for stamp, passage in passages.items() if quote in passage],
                              reason="인용한 전사 구간에서 이 표현의 정확한 문자열을 찾지 못함; 의미 판정은 원문 대조 필요"))
    return hints
