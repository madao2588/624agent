"""Domain errors with stable HTTP mappings."""


class RequestConflictError(RuntimeError):
    """A request ID was reused with a different payload."""


class RetrievalProviderError(RuntimeError):
    """An external retrieval provider failed without exposing private input."""


class EmbeddingServiceError(RetrievalProviderError):
    """The configured embedding service could not produce valid vectors."""


class QueryExpansionServiceError(RetrievalProviderError):
    """The configured query-expansion service could not produce valid terms."""


class EvaluationServiceError(RetrievalProviderError):
    """The fixed evaluation provider failed without leaking private input."""
