from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from itertools import pairwise

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE)
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "does", "for", "from",
    "happen", "how", "i", "in", "is", "it", "of", "on", "or", "the", "this",
    "to", "was", "what", "when", "why", "with",
}


def tokenize(value: str, *, remove_stop_words: bool = True) -> list[str]:
    tokens = [match.group(0).lower() for match in TOKEN_PATTERN.finditer(value)]
    if not remove_stop_words:
        return tokens
    return [token for token in tokens if token not in STOP_WORDS]


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def hashed_embedding(value: str, dimensions: int = 96) -> list[float]:
    """Dependency-free semantic-ish embedding suitable for deterministic demo mode."""
    vector = [0.0] * dimensions
    tokens = tokenize(value)
    expanded = tokens + [f"{a}_{b}" for a, b in pairwise(tokens)]
    for token in expanded:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1 if digest[4] % 2 else -1
        vector[index] += sign * (1.4 if "_" in token else 1.0)
    return vector


def jaccard(left: list[str], right: list[str]) -> float:
    a, b = set(left), set(right)
    return len(a & b) / len(a | b) if a or b else 0.0


def term_coverage(query_terms: list[str], content: str) -> float:
    wanted = set(query_terms)
    present = set(tokenize(content))
    return len(wanted & present) / len(wanted) if wanted else 1.0


def normalized_counter(value: str) -> Counter[str]:
    return Counter(tokenize(value))
