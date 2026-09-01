"""Domain errors with stable HTTP mappings."""


class RequestConflictError(RuntimeError):
    """A request ID was reused with a different payload."""
