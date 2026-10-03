#!/bin/sh
# Runs Storykeeper using the private Python environment that setup.sh made, so
# there is nothing to "activate" and nothing to remember.
#
# (It is called storykeeper.sh rather than plain storykeeper because the folder
# holding the program's own code is already called storykeeper.)
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHONPATH="$HERE:$PYTHONPATH"
export PYTHONPATH

if [ -x "$HERE/.venv/bin/python" ]; then
    exec "$HERE/.venv/bin/python" -m storykeeper "$@"
fi

cat <<'MESSAGE'

  Storykeeper has not been set up on this computer yet.

  Run  ./setup.sh  in this folder first - it only takes a minute.

MESSAGE
exit 1
