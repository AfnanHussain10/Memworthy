"""Small BM25 ranker used by local stores; no embeddings required."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
STOPWORDS = frozenset(
    "a an the i im i'm me my we our you your he she it its they them their is am are was were "
    "be been to of in on at for and or but with this that these those just so do did does "
    "have has had will would can could should not no yes it's don't i've i'll i'd".split()
)


def tokens(text: str) -> list[str]:
    """Lowercase word tokens without stopwords."""
    return [t for t in _WORD.findall(text.lower()) if t not in STOPWORDS]


def bm25_rank(query: str, docs: Sequence[str], k: int, k1: float = 1.5,
              b: float = 0.75) -> list[tuple[int, float]]:
    """Return up to ``k`` (index, score) pairs with positive BM25 score, best first."""
    q = tokens(query)
    if not q or not docs:
        return []
    doc_tokens = [tokens(d) for d in docs]
    n = len(docs)
    avgdl = sum(len(d) for d in doc_tokens) / n or 1.0
    df: Counter[str] = Counter()
    for d in doc_tokens:
        df.update(set(d))
    scores: list[tuple[int, float]] = []
    for i, d in enumerate(doc_tokens):
        tf = Counter(d)
        s = 0.0
        for term in set(q):
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            f = tf[term]
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avgdl))
        if s > 0:
            scores.append((i, s))
    scores.sort(key=lambda x: (-x[1], x[0]))
    return scores[:k]
