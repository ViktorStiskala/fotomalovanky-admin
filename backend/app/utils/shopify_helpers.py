"""Shopify-related utility functions."""


def build_customer_name(first_name: str | None, last_name: str | None) -> str | None:
    """Build full customer name from first and last name.

    Args:
        first_name: Customer's first name (can be None)
        last_name: Customer's last name (can be None)

    Returns:
        Full name as "First Last", or None if both are empty
    """
    first = first_name or ""
    last = last_name or ""
    full_name = f"{first} {last}".strip()
    return full_name or None
