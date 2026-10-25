"""Sparse lexical vectors for hybrid retrieval (D-064).

Each chunk gets a sparse vector over hashed word tokens whose weights are the BM25
term-frequency part (saturated and length-normalised); Qdrant applies the inverse
document frequency at query time (`Modifier.IDF`), so together they score like BM25.
A question becomes a sparse vector with weight 1 per distinct token. Lexical scores
only re-order candidates: whether a chunk is evidence is still decided by its dense
(best sub-unit cosine) score and `MIN_RETRIEVAL_SCORE`.
"""

from __future__ import annotations

import re
import zlib
from collections import Counter

K1 = 1.2
B = 0.75
AVERAGE_TOKENS = 120.0  # fixed reference length (chunks are at most CHUNK_SIZE_TOKENS)

_TOKEN = re.compile(r"[^\W_]+(?:[_'][^\W_]+)*")
# Function words carry no topical signal; question words would match every chunk.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "might",
        "must",
        "not",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)


def tokens(text: str) -> list[str]:
    """Lower-cased word tokens without stopwords or single characters."""
    words = (match.group(0).lower() for match in _TOKEN.finditer(text))
    return [w for w in words if len(w) > 1 and w not in _STOPWORDS]


def _index(token: str) -> int:
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


def document_vector(text: str) -> tuple[list[int], list[float]]:
    counts = Counter(_index(t) for t in tokens(text))
    length = sum(counts.values()) or 1
    norm = K1 * (1 - B + B * length / AVERAGE_TOKENS)
    indices = sorted(counts)
    return indices, [counts[i] * (K1 + 1) / (counts[i] + norm) for i in indices]


def query_vector(text: str) -> tuple[list[int], list[float]]:
    indices = sorted({_index(t) for t in tokens(text)})
    return indices, [1.0] * len(indices)


def reciprocal_rank_fusion(*rankings: list[str], k: int = 60) -> list[str]:
    """Combine rankings of IDs; an ID's score is the sum of 1 / (k + rank)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]
