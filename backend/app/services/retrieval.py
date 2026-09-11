from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from app.models import Document, QueryProfile, SearchResult, StrategyName
from app.services.text import cosine, hashed_embedding, tokenize


class Corpus:
    def __init__(self, path: Path, *, demo_mode: bool = False):
        raw_bytes = path.read_bytes()
        raw_documents = json.loads(raw_bytes.decode("utf-8"))
        self.documents = [Document.model_validate(item) for item in raw_documents]
        self.demo_mode = demo_mode
        self.version = hashlib.sha256(raw_bytes).hexdigest()[:16]
        self._tokens = {
            doc.id: tokenize(f"{doc.title} {doc.content} {' '.join(doc.tags)}", remove_stop_words=False)
            for doc in self.documents
        }
        self._embeddings = {
            doc.id: hashed_embedding(f"{doc.title} {doc.content} {' '.join(doc.tags)}")
            for doc in self.documents
        }

    def _bm25_scores(self, profile: QueryProfile) -> dict[str, float]:
        query_terms = tokenize(profile.raw_query, remove_stop_words=False)
        lengths = [len(self._tokens[doc.id]) for doc in self.documents]
        average_length = sum(lengths) / len(lengths)
        scores: dict[str, float] = {}
        for document in self.documents:
            terms = self._tokens[document.id]
            counts = Counter(terms)
            score = 0.0
            for term in query_terms:
                frequency = counts[term]
                containing = sum(term in self._tokens[item.id] for item in self.documents)
                inverse_frequency = math.log(1 + (len(self.documents) - containing + 0.5) / (containing + 0.5))
                denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(terms) / average_length)
                score += inverse_frequency * (frequency * 2.5 / denominator if denominator else 0)
            scores[document.id] = score
        maximum = max(scores.values(), default=1.0)
        return {key: value / maximum if maximum else 0.0 for key, value in scores.items()}

    def _dense_scores(self, profile: QueryProfile) -> dict[str, float]:
        query_vector = hashed_embedding(profile.raw_query)
        raw = {doc.id: max(0.0, cosine(query_vector, self._embeddings[doc.id])) for doc in self.documents}
        maximum = max(raw.values(), default=1.0)
        return {key: value / maximum if maximum else 0.0 for key, value in raw.items()}

    def search(self, profile: QueryProfile, strategy: StrategyName, top_k: int) -> list[SearchResult]:
        dense = self._dense_scores(profile)
        lexical = self._bm25_scores(profile)
        newest = max(doc.published_at for doc in self.documents)
        scored: list[tuple[Document, float, list[str]]] = []
        for document in self.documents:
            reasons: list[str] = []
            if strategy is StrategyName.DENSE:
                # Fault injection is an explicit demo-only feature. A normal local
                # deployment must report the actual deterministic retrieval ranking.
                exact_penalty = 0.52 if self.demo_mode and profile.exact_identifiers and any(
                    identifier.lower() in self._tokens[document.id] for identifier in profile.exact_identifiers
                ) else 1.0
                score = dense[document.id] * exact_penalty
                # Reproduce an index-freshness failure: the baseline semantic index trails
                # newly effective material until the freshness-aware repair is selected.
                if self.demo_mode and profile.current_intent and "current" in document.tags:
                    score *= 0.58
                reasons.append("semantic similarity")
            elif strategy is StrategyName.BM25:
                score = lexical[document.id]
                reasons.append("exact/full-text match")
            else:
                score = 0.58 * lexical[document.id] + 0.42 * dense[document.id]
                reasons.extend(["lexical match", "semantic similarity"])

            age_days = max(0, (newest - document.published_at).days)
            freshness = math.exp(-age_days / 730)
            if strategy is StrategyName.FRESHNESS:
                score = 0.50 * lexical[document.id] + 0.25 * dense[document.id] + 0.25 * freshness
                reasons.append("freshness boost")
            elif strategy is StrategyName.HYBRID_RERANK:
                identifier_hit = any(
                    identifier.lower() in self._tokens[document.id] for identifier in profile.exact_identifiers
                )
                score += 0.20 if identifier_hit else 0
                score += 0.12 * freshness if profile.current_intent else 0
                reasons.append("intent-aware rerank")
            scored.append((document, score, reasons))

        scored.sort(key=lambda item: (item[1], item[0].published_at), reverse=True)
        maximum = scored[0][1] if scored and scored[0][1] else 1.0
        return [
            SearchResult(
                document=document,
                score=round(score / maximum, 4),
                rank=index,
                strategy=strategy,
                reasons=reasons,
            )
            for index, (document, score, reasons) in enumerate(scored[:top_k], start=1)
        ]
