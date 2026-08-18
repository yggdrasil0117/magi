"""Tests for provider retry classification and sanitized invocation records."""

from __future__ import annotations

import unittest

from magi.agents import ModelTokenUsage, RetryPolicy


class RetryPolicyTests(unittest.TestCase):
    def test_retry_after_header_takes_priority(self) -> None:
        class Response:
            headers = {"Retry-After": "3.5"}

        class RateLimitError(Exception):
            response = Response()

        policy = RetryPolicy(initial_backoff_seconds=0.25)
        error = RateLimitError()

        self.assertTrue(policy.is_transient(error))
        self.assertEqual(policy.delay_seconds(error, attempt=1), 3.5)

    def test_bad_request_is_not_transient(self) -> None:
        class BadRequestError(Exception):
            pass

        self.assertFalse(RetryPolicy().is_transient(BadRequestError()))

    def test_usage_total_cannot_be_smaller_than_parts(self) -> None:
        with self.assertRaisesRegex(ValueError, "total_tokens"):
            ModelTokenUsage(input_tokens=4, output_tokens=3, total_tokens=6)


if __name__ == "__main__":
    unittest.main()
