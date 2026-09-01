class LLMError(Exception):
    """Raised when the LLM backend cannot be reached or returns unusable output.

    Callers (see ``pipeline.py``) catch this to fail open — skipping a round
    rather than blocking the student from seeing partial feedback.
    """
