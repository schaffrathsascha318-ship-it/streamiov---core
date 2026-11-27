"""Shared parsing for observed test-command exit codes."""
from __future__ import annotations

import re

EXIT_CODE_PATTERN = re.compile(r"^exit_code=(0|[1-9]\d*)(?:\s|$)")


def observed_successful_test(output: object) -> bool:
    """Return True only when sanitized tool output starts with exit_code=0."""
    if not isinstance(output, str):
        return False
    match = EXIT_CODE_PATTERN.match(output.strip())
    return bool(match and int(match.group(1)) == 0)
