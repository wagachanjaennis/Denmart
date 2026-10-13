"""Consistent public branding defaults for storefronts and manager surfaces."""


def brand_display_name(value, default="Denmart"):
    """Use Denmart instead of the old seeded Toror Mart default, but respect new custom names."""
    name = str(value or "").strip()
    if not name or name.casefold() == "toror mart":
        return default
    return name


def brand_display_copy(value, brand_name):
    """Make saved public copy follow the current configured display name."""
    import re
    text = str(value or "")
    return re.sub(r"\b(?:Toror\s+Mart|Denmart)\b", str(brand_name or "Denmart"), text, flags=re.IGNORECASE)
