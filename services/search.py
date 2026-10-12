"""Relevant, field-aware product search shared by shop, POS and admin.

Every query token must match a token belonging to the same product. This avoids
weak fuzzy matches (e.g. a search for "tissue paper" showing bread or milk),
while still supporting prefixes during typing and small typos in longer words.
"""
import re
import unicodedata
from difflib import SequenceMatcher


def normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return value


def _words(value):
    return normalize_text(value).split()


def _token_match(query_word, text_words):
    """Best token score; short tokens only match exactly or by prefix."""
    if not query_word or not text_words:
        return 0.0
    best = 0.0
    for word in text_words:
        if word == query_word:
            score = 1.0
        elif len(query_word) >= 2 and (word.startswith(query_word) or query_word.startswith(word)):
            # Live search can match incomplete words such as "pap" -> "paper".
            score = 0.93 + 0.06 * min(len(query_word), len(word)) / max(len(query_word), len(word))
        elif len(query_word) >= 4 and len(word) >= 4:
            ratio = SequenceMatcher(None, query_word, word).ratio()
            score = ratio if ratio >= 0.82 else 0.0
        else:
            score = 0.0
        best = max(best, score)
    return best


def _score(query, product, aliases=()):
    q = normalize_text(query)
    if not q:
        return 0.0
    q_words = q.split()
    fields = [
        ("name", normalize_text(getattr(product, "name", "")), 1.00),
        ("brand", normalize_text(getattr(product, "brand", "")), 0.90),
        ("alias", "", 0.97),
        ("sku", normalize_text(getattr(product, "sku", "")), 0.90),
        ("barcode", normalize_text(getattr(product, "barcode", "")), 0.90),
        ("keywords", normalize_text(getattr(product, "search_keywords", "")), 0.84),
        ("description", normalize_text(getattr(product, "description", "")), 0.70),
    ]
    alias_values = [normalize_text(a) for a in (aliases or ()) if normalize_text(a)]
    field_values = [(name, value, weight) for name, value, weight in fields if value]
    field_values.extend(("alias", value, 0.97) for value in alias_values)

    # Highest priority for a direct phrase match in a product's important fields.
    for field_name, value, weight in field_values:
        if value == q:
            return min(1.0, 0.96 + 0.04 * weight)
        if len(q_words) > 1 and q in value:
            return min(0.995, 0.93 + 0.06 * weight)

    # Each query word must be grounded in one of this product's own fields.
    # Keep all tokens together across fields (e.g. brand + name is valid).
    all_words = []
    for _, value, _ in field_values:
        all_words.extend(value.split())
    token_scores = [_token_match(word, all_words) for word in q_words]
    if not token_scores or any(score < 0.80 for score in token_scores):
        return 0.0

    # Prefer names/brands over matches only in description/search metadata.
    main_words = []
    for field_name, value, weight in field_values:
        field_words = value.split()
        if field_name in {"name", "brand", "alias", "sku", "barcode"}:
            main_words.extend(field_words)
    main_scores = [_token_match(word, main_words) for word in q_words]
    main_coverage = sum(score >= 0.80 for score in main_scores) / len(q_words)
    all_average = sum(token_scores) / len(token_scores)
    score = 0.76 * all_average + 0.24 * main_coverage
    # Full token coverage is mandatory; product with only "milk" cannot match
    # "tissue paper", regardless of how good one token looks.
    return min(0.99, score)


def forgiving_rank(rows, query, aliases_by_product=None, limit=300, minimum=0.72):
    """Return only relevant rows, ranked by match quality then product name."""
    rows = list(rows)
    if not query or not normalize_text(query):
        return sorted(rows, key=lambda r: (getattr(getattr(r, "product", None), "name", "") or "").lower())[:limit]
    aliases_by_product = aliases_by_product or {}
    scored = []
    for row in rows:
        score = _score(query, row.product, aliases_by_product.get(row.product_id, ()))
        if score >= minimum:
            scored.append((score, (row.product.name or "").lower(), row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored[:limit]]
