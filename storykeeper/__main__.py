"""Allows `python -m storykeeper` for people who have not installed the command."""

import sys

# Checked here, before anything else is imported, so that an old Python gets a
# plain sentence rather than a traceback from deep inside the package.
if sys.version_info < (3, 11):  # pragma: no cover
    sys.stderr.write(
        "\n  Storykeeper needs Python 3.11 or newer, but this is Python "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n\n"
        "  Install a current Python from https://www.python.org/downloads/\n"
        "  and run the setup script again.\n\n"
    )
    sys.exit(1)

from .cli import entry_point  # noqa: E402

if __name__ == "__main__":
    entry_point()
