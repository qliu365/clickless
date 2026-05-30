#!/bin/bash
# 打包 OfficeLego 为 macOS .app，并生成 zip 安装包
set -e
cd "$(dirname "$0")"

echo ">>> 安装打包依赖..."
pip3 install -r requirements.txt pyinstaller -q

echo ">>> 开始打包..."
pyinstaller --noconfirm --clean --windowed --name OfficeLego \
  --osx-bundle-identifier com.officelego.app \
  --hidden-import=pynput.keyboard._darwin \
  --hidden-import=pynput.mouse._darwin \
  --hidden-import=ApplicationServices \
  --hidden-import=Quartz \
  --exclude-module keyboard \
  main.py

echo ">>> 生成 zip..."
cd dist
rm -f OfficeLego-mac.zip
zip -r OfficeLego-mac.zip OfficeLego.app

echo ""
echo "完成！安装包位置："
echo "  $(pwd)/OfficeLego-mac.zip"
echo "  $(pwd)/OfficeLego.app"
