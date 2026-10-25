"""Deterministic acceptance check for generated answers (D-071).

An answer is accepted as evidence-grounded only if

1. it cites at least one supplied passage (`[Sn]` with n within the evidence),
2. it cites no identifier outside the evidence (`[S7]` with four passages),
3. every number it states occurs in the text the model received (after withholding,
   D-069), in the question, or as a page number of a supplied passage, and
4. every page it names ("page 4", "p. 4", "pp. 12-14") is the page of a supplied passage
   or is mentioned in the supplied text.

Rule 3 is a narrow grounding test: it catches invented or relayed values (an injected
"5,000" that was withheld cannot reappear), not wrong statements built from real
values. Computed values (a difference of two stated prices) fail it; the pipeline's one
repair attempt asks for stated values only. Citations prove only that a passage was
named, not that it supports the sentence; semantic support is left to the evaluation.
"""

from __future__ import annotations

import re

from app.retrieval.vector_store import RetrievedChunk

_CITATION = re.compile(r"\[(S\d+)\]")
_SOURCE_LABEL = re.compile(r"\bS\d+\b")
_THOUSANDS = re.compile(r"(?<=\d)[, \u00a0\u202f](?=\d{3}(?!\d))")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_PAGE = re.compile(
    r"\b(?:pages?|pp?\.)\s*(\d+)(?:\s*(?:-|\u2013|\u2014|to|and|&|,)\s*(\d+))?", re.IGNORECASE
)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}  # fmt: skip
_NUMBER_WORD = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)


def _canonical(number: str) -> str:
    # "48.0" and "48" are the same value; "0.30" and "0.3" too.
    return number.rstrip("0").rstrip(".") if "." in number else number.lstrip("0") or "0"


def numbers_in(text: str) -> set[str]:
    """Numeric values written with digits ("5,000" -> "5000"; citations ignored)."""
    text = _THOUSANDS.sub("", _SOURCE_LABEL.sub(" ", _CITATION.sub(" ", text)))
    return {_canonical(n) for n in _NUMBER.findall(text)}


def _stated_numbers(text: str) -> set[str]:
    values = numbers_in(text)
    values.update(str(_NUMBER_WORDS[w.lower()]) for w in _NUMBER_WORD.findall(text))
    return values


def _pages_named(answer: str) -> set[int]:
    pages: set[int] = set()
    for match in _PAGE.finditer(answer):
        # A range ("pp. 12-16") is checked at its ends, a list at each page.
        pages.add(int(match.group(1)))
        if match.group(2):
            pages.add(int(match.group(2)))
    return pages


def check_answer(
    answer: str, evidence: list[RetrievedChunk], model_texts: list[str], question: str
) -> list[str]:
    """Problems that prevent accepting `answer`; empty when it passes.

    `model_texts[i]` is the text the model received for `evidence[i]`.
    """
    valid = {f"S{i + 1}" for i in range(len(evidence))}
    cited = list(dict.fromkeys(_CITATION.findall(answer)))
    problems: list[str] = []
    invalid = [sid for sid in cited if sid not in valid]
    if invalid:
        problems.append("it cited identifiers that are not in the evidence: " + ", ".join(invalid))
    if not any(sid in valid for sid in cited):
        problems.append("it cited no evidence passage")

    supplied = " ".join(model_texts)
    pages = {c.page_number for c in evidence if c.page_number is not None}
    named_pages = _pages_named(answer)
    mentioned_pages = _pages_named(supplied)
    wrong_pages = sorted(p for p in named_pages if p not in pages and p not in mentioned_pages)
    if wrong_pages:
        problems.append(
            "it named pages that no passage is on: " + ", ".join(str(p) for p in wrong_pages)
        )

    allowed = _stated_numbers(supplied) | _stated_numbers(question)
    allowed |= {str(p) for p in pages | named_pages}
    unsupported = sorted(numbers_in(answer) - allowed, key=lambda n: (len(n), n))
    if unsupported:
        problems.append(
            "it stated values that the passages do not contain: " + ", ".join(unsupported)
        )
    return problems
