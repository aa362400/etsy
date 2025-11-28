#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "PyInstaller 未安装，请运行 'pip install -r requirements-packaging.txt'" >&2
  exit 1
fi

# 将样例商品文件打包到可执行文件旁，便于快速复制修改
PYINSTALLER_CMD=(
  pyinstaller
  --name etsy-lister
  --onefile
  --add-data "samples/product.yaml:samples"
  etsy_lister.py
)

"${PYINSTALLER_CMD[@]}"

echo "\n构建完成，可执行文件位于 dist/etsy-lister".
