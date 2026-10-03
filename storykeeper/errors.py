"""The one exception type Storykeeper raises on purpose.

The people using this are writers, not developers. Every failure this tool can
produce should tell them what to do next, in plain words. The CLI catches StorykeeperError and prints
``message`` followed by ``hint`` — no traceback, ever. If you find yourself
letting a raw exception escape, wrap it here instead.
"""

from __future__ import annotations


class StorykeeperError(Exception):
    """A problem the user can actually do something about."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message if not self.hint else f"{self.message}\n\n{self.hint}"
