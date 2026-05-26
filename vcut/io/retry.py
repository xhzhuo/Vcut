"""Simple retry utility with exponential backoff."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


def retry_call(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    retryable: tuple[type[Exception], ...] = (RuntimeError,),
    **kwargs: Any,
) -> Any:
    """Call *fn* with exponential-backoff retry.

    Retries up to *max_retries* times when *fn* raises an exception whose
    type is in *retryable*.  Non-retryable exceptions propagate immediately.

    Backoff sequence: base_delay, base_delay*2, base_delay*4, ...
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except retryable as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1,
                    max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Attempt %d/%d failed: %s — giving up",
                    attempt + 1,
                    max_retries,
                    exc,
                )
    raise last_exc  # type: ignore[misc]
