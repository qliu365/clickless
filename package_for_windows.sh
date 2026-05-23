#!/bin/bash
# 打包源码发给 Windows 同事，对方解压后双击 build_win.bat 即可生成 exe
set -e
cd "$(dirname "$0")"

OUT="Clickless-Windows-src.zip"
rm -f "$OUT"

zip -r "$OUT" \
  main.py gui.py recorder.py player.py storage.py permissions.py \
  mouse_click.py click_marker.py recording_floater.py text_capture.py \
  requirements.txt build_win.bat 同事请看.txt \
  -x "**/__pycache__/*" "**/*.pyc"

echo ""
echo "已生成: $(pwd)/$OUT"
echo ""
echo "发给同事后让他:"
echo "  1. 解压"
echo "  2. 双击 build_win.bat"
echo "  3. 使用 dist\\Clickless-win.zip 或 dist\\Clickless\\Clickless.exe"
