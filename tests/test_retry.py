"""Tests for retry utility."""

from __future__ import annotations

import pytest

from vcut.io.retry import retry_call


class TestRetryCall:
    def test_success_on_first_try(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = retry_call(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 1

    def test_success_after_retry(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("temporary error")
            return "ok"

        result = retry_call(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 3

    def test_non_retryable_exception_propagates_immediately(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("non-retryable")

        with pytest.raises(ValueError, match="non-retryable"):
            retry_call(fn, max_retries=3, base_delay=0.01, retryable=(RuntimeError,))
        assert call_count == 1

    def test_retryable_exception_retries(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("retryable")

        with pytest.raises(RuntimeError, match="retryable"):
            retry_call(fn, max_retries=3, base_delay=0.01, retryable=(RuntimeError,))
        assert call_count == 3

    def test_max_retries_zero_fails_immediately(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("error")

        with pytest.raises(RuntimeError):
            retry_call(fn, max_retries=1, base_delay=0.01)
        assert call_count == 1

    def test_args_passed_correctly(self):
        def fn(a, b, c=None):
            return (a, b, c)

        result = retry_call(fn, 1, 2, c=3, max_retries=1, base_delay=0.01)
        assert result == (1, 2, 3)

    def test_multiple_retryable_types(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("error 1")
            if call_count == 2:
                raise ValueError("error 2")
            return "ok"

        with pytest.raises(ValueError):
            retry_call(fn, max_retries=3, base_delay=0.01, retryable=(RuntimeError,))
        assert call_count == 2

    def test_last_exception_raised(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"error {call_count}")

        with pytest.raises(RuntimeError, match="error 3"):
            retry_call(fn, max_retries=3, base_delay=0.01)
