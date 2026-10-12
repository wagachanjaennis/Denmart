"""Focused regression tests for Denmart product-search relevance."""
from services.search import forgiving_rank


class Product:
    def __init__(self, name, brand="", keywords="", description=""):
        self.name = name
        self.brand = brand
        self.search_keywords = keywords
        self.description = description
        self.sku = ""
        self.barcode = ""


class StoreRow:
    def __init__(self, product):
        self.product = product
        self.product_id = product.name


def sample_rows():
    return [
        StoreRow(Product("Tissue Paper 2 Ply", "Softcare", "tissue paper toilet paper")),
        StoreRow(Product("Tissue Roll", "Hanan", "tissue roll bathroom")),
        StoreRow(Product("Fresh Milk", "Brookside", "milk dairy")),
        StoreRow(Product("White Bread", "Broadways", "bread bakery")),
        StoreRow(Product("UHT Milk 1L", "Tuzo", "milk")),
    ]


def names(rows):
    return [row.product.name for row in rows]


def test_multiword_search_does_not_return_unrelated_items():
    result = forgiving_rank(sample_rows(), "tissue paper")
    assert names(result) == ["Tissue Paper 2 Ply"]


def test_live_prefixes_find_results_while_typing():
    result = forgiving_rank(sample_rows(), "tissue pa")
    assert names(result) == ["Tissue Paper 2 Ply"]


def test_single_word_search_finds_relevant_products_only():
    result = forgiving_rank(sample_rows(), "milk")
    assert set(names(result)) == {"Fresh Milk", "UHT Milk 1L"}


def test_minor_typo_remains_searchable_without_unrelated_results():
    result = forgiving_rank(sample_rows(), "tisssue paper")
    assert names(result) == ["Tissue Paper 2 Ply"]


def test_missing_query_returns_alphabetical_results():
    result = forgiving_rank(sample_rows(), "")
    assert names(result) == sorted(names(result), key=str.lower)
