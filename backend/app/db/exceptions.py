"""Database-related exceptions."""


class MercureContextError(Exception):
    """Raised when Mercure context is missing or incomplete.

    This error is raised when:
    - A tracked field changes but set_mercure_context() was not called
    - set_mercure_context() is called but required context fields are missing
    """

    pass
