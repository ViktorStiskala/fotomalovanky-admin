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


def normalize_order_number(order_number: str) -> str:
    """Normalize order number to include '#' prefix.

    Shopify order numbers are stored with '#' prefix (e.g., "#1270"),
    but API requests may come without it.

    Args:
        order_number: Order number with or without '#' prefix

    Returns:
        Order number with '#' prefix
    """
    if order_number.startswith("#"):
        return order_number
    return f"#{order_number}"
