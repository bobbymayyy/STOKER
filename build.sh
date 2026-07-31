#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV=${STOKER_VENV:-"$ROOT_DIR/.venv"}
PYTHON=${PYTHON:-python3}

if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$ROOT_DIR/.env"
    set +a
fi

if "$PYTHON" -c 'import yaml, jinja2, jsonschema' >/dev/null 2>&1; then
    export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
    exec "$PYTHON" -m stoker_builder.cli "$@"
fi

if [ ! -x "$VENV/bin/python" ]; then
    "$PYTHON" -m venv "$VENV"
fi

if ! "$VENV/bin/python" -c 'import yaml, jinja2, jsonschema' >/dev/null 2>&1; then
    "$VENV/bin/pip" install -r "$ROOT_DIR/requirements.txt"
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m stoker_builder.cli "$@"
