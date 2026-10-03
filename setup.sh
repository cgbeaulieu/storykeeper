#!/bin/sh
# ---------------------------------------------------------------------------
#  Storykeeper setup for Mac and Linux.
#
#  Run it from a terminal, in this folder:
#
#      ./setup.sh
#
#  It creates a private Python environment inside this folder and installs the
#  four packages Storykeeper needs. It changes nothing else on your computer,
#  and it does not touch your writing.
# ---------------------------------------------------------------------------
set -e
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

echo
echo "  Storykeeper setup"
echo "  ================="
echo

# --- 1. Find a Python that is new enough ------------------------------------

PY=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    cat <<'MESSAGE'
  PROBLEM: Python 3.11 or newer was not found on this computer.

  What to do:

    On a Mac, the simplest route is to install Homebrew from
    https://brew.sh and then run:

        brew install python

    On Linux, use your usual package manager, for example:

        sudo apt install python3 python3-venv     (Debian, Ubuntu, Mint)
        sudo dnf install python3                  (Fedora)

  Then run ./setup.sh again.
MESSAGE
    exit 1
fi

echo "  Found $("$PY" -c 'import sys;print("Python "+sys.version.split()[0])')."
echo

# --- 2. Create the private environment ---------------------------------------

if [ -x ".venv/bin/python" ]; then
    echo "  Using the Python environment that is already here."
else
    echo "  Creating a private Python environment in .venv ..."
    if ! "$PY" -m venv .venv; then
        cat <<'MESSAGE'

  PROBLEM: the environment could not be created.

  On Debian or Ubuntu this usually means one more package is needed:

      sudo apt install python3-venv

  Then run ./setup.sh again.
MESSAGE
        exit 1
    fi
fi

VPY="$PWD/.venv/bin/python"

# --- 3. Install what Storykeeper needs ---------------------------------------

echo
echo "  Installing the pieces Storykeeper needs. This takes a minute or two"
echo "  and needs the internet, but only this once."
echo

"$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check
if ! "$VPY" -m pip install -r requirements.txt --disable-pip-version-check; then
    echo
    echo "  PROBLEM: the installation did not finish."
    echo "  The usual cause is no internet connection. Check that, then run"
    echo "  ./setup.sh again."
    exit 1
fi

chmod +x storykeeper.sh 2>/dev/null || true

# --- 4. Make the library folders ---------------------------------------------

for folder in manuscript characters history culture locations plot other; do
    mkdir -p "library/$folder"
done

# --- 5. Say what is left to do -----------------------------------------------

echo
echo "  =========================================================="
echo "  Setup is done."
echo "  =========================================================="
echo

if command -v ollama >/dev/null 2>&1; then
    echo "  Ollama is installed. If you have not already, download a model:"
    echo
    echo "      ollama pull llama3.1:8b"
    echo
    echo "  (That is the default. README.md, under \"Choosing a model\", says"
    echo "  which one suits your computer best.)"
    echo
else
    echo "  STILL TO DO - install Ollama, which runs the AI on this computer:"
    echo
    echo "    1. Go to  https://ollama.com  and install it."
    echo "    2. Then run:   ollama pull llama3.1:8b"
    echo "       (that is a 5 GB download, once. README.md, under \"Choosing a"
    echo "       model\", says which model suits your computer best.)"
    echo
fi

cat <<'MESSAGE'
  THEN:

    1. Put your writing in the "library" folder, in the subfolders that are
       now there. See library/README.md.

    2. In this folder, run:

           ./storykeeper.sh index
           ./storykeeper.sh chat

MESSAGE
