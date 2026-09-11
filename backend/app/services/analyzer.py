from __future__ import annotations

from datetime import UTC, datetime

from app.models import (
    Diagnosis,
    FailureType,
    QualitySignals,
    QueryProfile,
    SearchResult,
)
from app.services.text import jaccard, term_coverage, tokenize


def _document_text(result: SearchResult) -> str:
    document = result.document
    return " ".join(
        [document.id, document.title, document.content, document.product,
         document.document_type, *document.tags]
    )


def _text_relevance(profile: QueryProfile, value: str) -> float:
    """Estimate relevance from evidence text, never from a strategy's score.

    ``SearchResult.score`` is normalized independently by each retrieval strategy,
    so comparing it across strategies (or trusting it as semantic truth) is invalid.
    This conservative lexical proxy is deterministic and makes that limitation clear.
    """
    query_terms = set(profile.terms)
    document_terms = set(tokenize(value))
    if not query_terms:
        return 0.0
    coverage = len(query_terms & document_terms) / len(query_terms)
    overlap = jaccard(list(query_terms), list(document_terms))
    return min(1.0, 0.7 * coverage + 0.3 * overlap)


def calculate_signals(
    profile: QueryProfile,
    results: list[SearchResult],
    *,
    reference_time: datetime | None = None,
) -> QualitySignals:
    if not results:
        return QualitySignals(
            exact_token_recall=0,
            semantic_relevance=0,
            evidence_coverage=0,
            diversity=0,
            metadata_match=0,
            freshness=0,
        )

    joined = [_document_text(item) for item in results]
    if profile.exact_identifiers:
        identifier_recalls: list[float] = []
        for identifier in profile.exact_identifiers:
            matching_ranks = [
                position for position, text in enumerate(joined, start=1)
                if identifier.lower() in tokenize(text, remove_stop_words=False)
            ]
            identifier_recalls.append(1 / min(matching_ranks) if matching_ranks else 0.0)
        exact_recall = sum(identifier_recalls) / len(identifier_recalls)
    else:
        exact_recall = 1.0

    semantic_relevance = sum(_text_relevance(profile, value) for value in joined[:3]) / min(3, len(results))
    evidence_coverage = max(term_coverage(profile.terms, value) for value in joined)
    pairs = [
        jaccard(tokenize(left), tokenize(right))
        for index, left in enumerate(joined)
        for right in joined[index + 1 :]
    ]
    diversity = 1 - (sum(pairs) / len(pairs) if pairs else 0)

    metadata_hits = 0
    for result in results:
        searchable = " ".join([result.document.product, result.document.document_type, *result.document.tags]).lower()
        if any(term in searchable for term in profile.terms):
            metadata_hits += 1
    metadata_match = metadata_hits / len(results)

    # Relative corpus freshness is deterministic: unless a caller supplies an
    # explicit clock, compare the top result to the newest evidence in this run.
    # The full Corpus can pass its own reference time when a deployment has one.
    now = reference_time or max(item.document.published_at for item in results)
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=UTC)
    top_age_days = max(0, (now - results[0].document.published_at).days)
    freshness = max(0.0, 1 - top_age_days / (365 * 3))
    return QualitySignals(
        exact_token_recall=round(exact_recall, 4),
        semantic_relevance=round(semantic_relevance, 4),
        evidence_coverage=round(evidence_coverage, 4),
        diversity=round(diversity, 4),
        metadata_match=round(metadata_match, 4),
        freshness=round(freshness, 4),
    )


def diagnose(profile: QueryProfile, results: list[SearchResult]) -> Diagnosis:
    signals = calculate_signals(profile, results)
    if profile.exact_identifiers and signals.exact_token_recall < 0.5:
        return Diagnosis(
            failure_type=FailureType.LEXICAL,
            confidence=round(1 - signals.exact_token_recall, 4),
            explanation="The baseline buried or missed an exact identifier; lexical retrieval is required.",
            signals=signals,
        )
    if profile.current_intent and signals.freshness < 0.72:
        return Diagnosis(
            failure_type=FailureType.STALE,
            confidence=round(1 - signals.freshness, 4),
            explanation="The top evidence is too old for a query asking for current information.",
            signals=signals,
        )
    if signals.evidence_coverage < 0.45:
        return Diagnosis(
            failure_type=FailureType.INSUFFICIENT,
            confidence=round(1 - signals.evidence_coverage, 4),
            explanation="The retrieved evidence does not cover enough of the query terms.",
            signals=signals,
        )
    return Diagnosis(
        failure_type=FailureType.NONE,
        confidence=0.82,
        explanation="The baseline evidence meets the configured quality thresholds.",
        signals=signals,
    )


def quality_score(profile: QueryProfile, signals: QualitySignals) -> float:
    weights = {
        "exact_token_recall": 0.28 if profile.exact_identifiers else 0.06,
        "semantic_relevance": 0.20,
        "evidence_coverage": 0.22,
        "diversity": 0.10,
        "metadata_match": 0.08,
        "freshness": 0.25 if profile.current_intent else 0.12,
    }
    total_weight = sum(weights.values())
    score = sum(getattr(signals, key) * weight for key, weight in weights.items()) / total_weight
    return round(min(1.0, score), 4)
