"""Forgiving catalogue search helpers.

Search is deliberately field-aware but forgiving: a query may match words
across name, brand, description, SKU, barcode, keywords and aliases. Typos are
handled with lightweight fuzzy scoring so the POS/storefront behave consistently.
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


def _best_word_score(query_word, text_words):
    if not query_word or not text_words:
        return 0.0
    best = 0.0
    for tw in text_words:
        if not tw:
            continue
        if tw == query_word:
            best = max(best, 1.0)
        elif query_word in tw or tw in query_word:
            shorter = min(len(query_word), len(tw))
            longer = max(len(query_word), len(tw))
            containment = shorter / max(longer, 1)
            best = max(best, 0.92 * containment + 0.08)
        best = max(best, SequenceMatcher(None, query_word, tw).ratio())
    return best


def _score(query, product, aliases=()):
    q = normalize_text(query)
    if not q:
        return 0.0
    q_words = q.split()
    fields = [
        ("name", normalize_text(product.name), 1.00),
        ("brand", normalize_text(product.brand), 0.88),
        ("keywords", normalize_text(product.search_keywords), 0.82),
        ("description", normalize_text(product.description), 0.72),
        ("sku", normalize_text(product.sku), 0.70),
        ("barcode", normalize_text(product.barcode), 0.70),
    ]
    alias_values = [normalize_text(a) for a in (aliases or ()) if normalize_text(a)]
    fields.extend(("alias", a, 0.95) for a in alias_values)

    # A query can legitimately span fields: e.g. "brookside mala" where
    # Brookside is the brand and Mala is the product name.
    composite = " ".join(v for _, v, _ in fields if v)
    composite_words = composite.split()
    if q == composite:
        return 1.0
    if q in composite:
        return 0.985

    per_word = [_best_word_score(qw, composite_words) for qw in q_words]
    if not per_word:
        return 0.0

    coverage = sum(1.0 for s in per_word if s >= 0.70) / len(per_word)
    avg_word = sum(per_word) / len(per_word)
    weakest = min(per_word)
    # Multi-word searches must account for most of the words. This prevents
    # a strong hit on just one word (for example "milk") from surfacing
    # unrelated products for a query such as "cooking oil".
    if len(q_words) > 1 and (coverage < 0.75 or weakest < 0.55):
        return 0.0
    score = 0.62 * avg_word + 0.28 * coverage + 0.10 * weakest

    # Reward exact/near-exact phrase matches in higher-value fields.
    for _, text, weight in fields:
        if not text:
            continue
        if q == text:
            return min(1.0, 0.995 * weight + 0.01)
        if q in text:
            score = max(score, 0.965 * weight)
        field_words = text.split()
        if field_words:
            field_word_scores = [_best_word_score(qw, field_words) for qw in q_words]
            field_coverage = sum(1.0 for s in field_word_scores if s >= 0.72) / len(q_words)
            field_avg = sum(field_word_scores) / len(q_words)
            if field_coverage == 1.0:
                score = max(score, (0.86 + 0.11 * field_avg) * weight)

    return min(1.0, score)


def forgiving_rank(rows, query, aliases_by_product=None, limit=300, minimum=0.48):
    """Return rows ranked by exact/partial/fuzzy relevance.

    The caller should already constrain rows to the correct business/store and
    availability. When a query is empty, preserve deterministic alphabetical
    ordering rather than returning arbitrary database order.
    """
    if not query:
        return sorted(list(rows), key=lambda r: r.product.name.lower())[:limit]
    aliases_by_product = aliases_by_product or {}
    scored = []
    for row in rows:
        score = _score(query, row.product, aliases_by_product.get(row.product_id, ()))
        if score >= minimum:
            scored.append((score, row.product.name.lower(), row))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [row for _, _, row in scored[:limit]]
