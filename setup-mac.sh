#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"

if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' '请先安装 uv，例如 brew install uv，然后重新运行本脚本。' \
        '其他官方安装方式：https://docs.astral.sh/uv/getting-started/installation/' >&2
    exit 1
fi

uv sync --locked
exec uv run --locked python -m agent_digest.setup_wizard
