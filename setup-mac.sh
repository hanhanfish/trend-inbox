#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

local_uv="$PWD/.setup/uv/uv"
if [ -x "$local_uv" ]; then
    uv="$local_uv"
elif command -v uv >/dev/null 2>&1; then
    uv="$(command -v uv)"
else
    read -r -p '需要在项目目录下载 uv，是否继续？[Y/n] ' answer
    case "$answer" in
        ''|[Yy]|[Yy][Ee][Ss]) ;;
        *) exit 1 ;;
    esac
    mkdir -p .setup/uv
    curl -fLsS https://astral.sh/uv/install.sh -o .setup/uv-install.sh
    UV_UNMANAGED_INSTALL="$PWD/.setup/uv" sh .setup/uv-install.sh
    uv="$local_uv"
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.setup/cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$PWD/.setup/python}"
"$uv" sync --locked
exec "$uv" run --locked python -m agent_digest.setup_wizard
