#!/usr/bin/env bash
# tt2 CLI 一键安装: curl -fsSL https://cli.tt2.li/install.sh | sh
set -euo pipefail

INSTALL_DIR="${TT2_INSTALL_DIR:-$HOME/.local/bin}"
BASE_URL="https://cli.tt2.li"

command -v curl >/dev/null || { echo "缺少 curl" >&2; exit 2; }
command -v tar >/dev/null || { echo "缺少 tar" >&2; exit 2; }

mkdir -p "$INSTALL_DIR"
curl -fsSL "$BASE_URL/tt2" -o "$INSTALL_DIR/tt2"
chmod +x "$INSTALL_DIR/tt2"

if ! echo "$PATH" | tr ':' '\n' | grep -qx "$INSTALL_DIR"; then
    echo "提示: 请将 $INSTALL_DIR 加入 PATH，例如:"
    echo "  echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> ~/.bashrc"
fi

echo "✓ tt2 已安装到 $INSTALL_DIR/tt2"
echo "下一步: tt2 login"
