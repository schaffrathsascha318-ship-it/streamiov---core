"""Unit tests for strict observed test exit-code parsing."""
import unittest

from ai.core.verification_evidence import observed_successful_test


class VerificationEvidenceTests(unittest.TestCase):
    def test_accepts_only_a_leading_successful_exit_code(self):
        self.assertTrue(observed_successful_test("exit_code=0\nRan 1 test\nOK"))
        self.assertTrue(observed_successful_test("exit_code=0\n"))

    def test_rejects_failure_even_when_success_text_appears_later(self):
        self.assertFalse(observed_successful_test("exit_code=1\nFAILED; expected exit_code=0"))
        self.assertFalse(observed_successful_test("TOOL_ERROR: exit_code=0"))
        self.assertFalse(observed_successful_test("note\nexit_code=0"))
        self.assertFalse(observed_successful_test("exit_code=00\nOK"))
        self.assertFalse(observed_successful_test(None))


if __name__ == "__main__":
    unittest.main()
