"""Storykeeper — a fully local question-answering system over your own writing.

Nothing in this package makes a network call at query time. See SPEC.md.
"""

__version__ = "1.0.0"

from .errors import StorykeeperError

__all__ = ["StorykeeperError", "__version__"]
