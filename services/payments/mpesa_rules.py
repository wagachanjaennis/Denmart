from decimal import Decimal

from services.payments.normalization import normalize_amount


PAYMENT_MATCHED = "PAYMENT_MATCHED / AUTO_APPROVED"
PAYMENT_UNMATCHED = "PAYMENT_UNMATCHED"
PAYMENT_AMBIGUOUS = "PAYMENT_AMBIGUOUS"
UNDERPAYMENT = "UNDERPAYMENT"
OVERPAYMENT = "OVERPAYMENT"
DUPLICATE = "DUPLICATE / ALREADY_PROCESSED"


def classify_phone_amount_candidates(received_amount, exact_candidates, phone_candidates):
    """Return the only automatic decision permitted by the matcher rules.

    ``exact_candidates`` contains candidates with both normalized phone and exact amount.
    ``phone_candidates`` contains every open candidate with the normalized phone.
    This function intentionally does not accept a name signal and cannot return PAID for
    an amount mismatch.
    """
    exact_count = len(exact_candidates)
    if exact_count == 1:
        return PAYMENT_MATCHED
    if exact_count > 1:
        return PAYMENT_AMBIGUOUS
    if not phone_candidates:
        return PAYMENT_UNMATCHED

    expected_amounts = {normalize_amount(row["expected_amount"]) for row in phone_candidates}
    expected_amounts.discard(None)
    if len(expected_amounts) != 1:
        return PAYMENT_AMBIGUOUS

    received = normalize_amount(received_amount)
    expected = next(iter(expected_amounts))
    if received is not None and received < expected:
        return UNDERPAYMENT
    if received is not None and received > expected:
        return OVERPAYMENT
    return PAYMENT_UNMATCHED
