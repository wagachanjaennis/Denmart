"""Focused rule tests for the rebuilt M-PESA auto-approval decision layer."""
from services.payments.mpesa_rules import (
    PAYMENT_MATCHED, PAYMENT_UNMATCHED, PAYMENT_AMBIGUOUS,
    UNDERPAYMENT, OVERPAYMENT,
    classify_phone_amount_candidates,
)
from services.payments.normalization import normalize_amount, normalize_ke_phone, normalize_person_name


def test_normalization():
    assert normalize_ke_phone("0732154678") == "254732154678"
    assert normalize_ke_phone("+254732154678") == "254732154678"
    assert normalize_ke_phone("254732154678") == "254732154678"
    assert normalize_amount("Ksh 1,000.00") == normalize_amount("1000") == normalize_amount("1000.00")
    assert normalize_person_name(" Jean   Promise ") == "JEAN PROMISE"


def test_exactly_one_is_auto_approved_without_name():
    candidates = [{"payment_id": "A", "expected_amount": "1000.00"}]
    assert classify_phone_amount_candidates("1000", candidates, candidates) == PAYMENT_MATCHED


def test_zero_exact_is_unmatched_when_phone_has_no_candidate():
    assert classify_phone_amount_candidates("1000", [], []) == PAYMENT_UNMATCHED


def test_multiple_exact_is_ambiguous():
    candidates = [
        {"payment_id": "A", "expected_amount": "1000.00"},
        {"payment_id": "B", "expected_amount": "1000.00"},
    ]
    assert classify_phone_amount_candidates("1000", candidates, candidates) == PAYMENT_AMBIGUOUS


def test_underpayment_and_overpayment_are_not_approved():
    phone = [{"payment_id": "A", "expected_amount": "1000.00"}]
    assert classify_phone_amount_candidates("900", [], phone) == UNDERPAYMENT
    assert classify_phone_amount_candidates("1100", [], phone) == OVERPAYMENT


def test_different_phone_candidate_amounts_are_ambiguous():
    phone = [
        {"payment_id": "A", "expected_amount": "1000.00"},
        {"payment_id": "B", "expected_amount": "1200.00"},
    ]
    assert classify_phone_amount_candidates("900", [], phone) == PAYMENT_AMBIGUOUS


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            globals()[name]()
    print("M-PESA RULE TESTS: PASS")
