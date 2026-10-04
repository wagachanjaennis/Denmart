from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


def normalize_ke_phone(value):
    """Return a canonical Kenyan mobile number as 2547XXXXXXXX/2541XXXXXXXX."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("254") and len(digits) == 12 and digits[3] in "17":
        return digits
    if digits.startswith("0") and len(digits) == 10 and digits[1] in "17":
        return "254" + digits[1:]
    if digits.startswith("7") and len(digits) == 9:
        return "254" + digits
    if digits.startswith("1") and len(digits) == 9:
        return "254" + digits
    return None


def normalize_amount(value):
    """Normalize monetary values such as 1000, 1000.00 or Ksh 1,000.00."""
    try:
        text = str(value or "0").strip()
        text = re.sub(r"^(?:KSHS?|KES)\s*", "", text, flags=re.IGNORECASE)
        text = text.replace(",", "")
        return Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def normalize_person_name(value):
    """Normalize a payer name for display/manual comparison only."""
    text = str(value or "").strip().upper()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(
        r"^(?:AIRTEL\s+MONEY|AIRTEL|M[-\s]?PESA|SAFARICOM)\s*(?:[-:|]+\s*)+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()
