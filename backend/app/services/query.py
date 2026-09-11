import re

from app.models import QueryProfile
from app.services.text import tokenize

IDENTIFIER_PATTERN = re.compile(r"\b[A-Z]{2,12}-\d{2,8}\b", re.IGNORECASE)
CURRENT_WORDS = {"current", "latest", "newest", "today", "now", "effective"}


def understand_query(query: str) -> QueryProfile:
    normalized = " ".join(query.strip().split())
    identifiers = [value.upper() for value in IDENTIFIER_PATTERN.findall(normalized)]
    terms = tokenize(normalized)
    current_intent = bool(CURRENT_WORDS.intersection(terms))
    if identifiers:
        query_type = "exact_identifier_troubleshooting"
    elif current_intent:
        query_type = "current_information"
    else:
        query_type = "semantic_question"
    identifier_prefixes = {item.split("-", maxsplit=1)[0].lower() for item in identifiers}
    if identifier_prefixes.intersection({"auth"}) or {"authentication", "sso", "oauth", "login"}.intersection(terms):
        domain = "authentication"
    elif {"refund", "billing", "payment", "policy"}.intersection(terms):
        domain = "billing"
    elif {"renderer", "render", "svg", "gpu"}.intersection(terms):
        domain = "renderer"
    elif {"checkout", "order", "cart"}.intersection(terms):
        domain = "checkout"
    else:
        # Avoid teaching one universal play for unrelated semantic questions.
        domain = "-".join(terms[:2]) or "general"
    # Keep plays reusable across identifiers in one family, while separating
    # time-sensitive requests from ordinary troubleshooting.
    signature = f"{query_type}:{domain}{':current' if current_intent else ''}"
    return QueryProfile(
        raw_query=query,
        normalized_query=normalized.lower(),
        query_type=query_type,
        signature=signature,
        domain=domain,
        exact_identifiers=identifiers,
        current_intent=current_intent,
        terms=terms,
    )
