#!/bin/bash
# 在 Mac 上一键打出 Windows 免 Python 安装包（GitHub Actions 云端构建）
set -e
cd "$(dirname "$0")"

GH="${GH:-gh}"
OUT="Clickless-win.zip"

if ! command -v "$GH" >/dev/null 2>&1; then
  echo "[错误] 未找到 gh，请先安装: brew install gh"
  exit 1
fi

if ! "$GH" auth status >/dev/null 2>&1; then
  echo ""
  echo "请先登录 GitHub（浏览器里点一下即可）："
  echo "  gh auth login"
  echo ""
  exit 1
fi

echo ">>> 准备 Git 仓库..."
git rev-parse --git-dir >/dev/null 2>&1 || git init
git branch -M main 2>/dev/null || true

if ! git remote get-url origin >/dev/null 2>&1; then
  echo ">>> 创建 GitHub 私有仓库并推送..."
  "$GH" repo create clickless --private --source=. --remote=origin --push
else
  echo ">>> 推送到 GitHub..."
  git add -A
  git diff --cached --quiet || git -c user.name="Clickless" -c user.email="build@local" commit -m "update"
  git push -u origin main
fi

echo ">>> 触发 Windows 云端打包（约 3-5 分钟）..."
"$GH" workflow run "Build Clickless"

sleep 3
RUN_ID=$("$GH" run list --workflow="Build Clickless" --limit 1 --json databaseId -q '.[0].databaseId')
echo ">>> 等待构建完成 (run #$RUN_ID)..."
"$GH" run watch "$RUN_ID"

echo ">>> 下载安装包..."
rm -rf .gh-artifacts
mkdir -p .gh-artifacts
"$GH" run download "$RUN_ID" --name Clickless-win --dir .gh-artifacts

if [ ! -f ".gh-artifacts/$OUT" ]; then
  echo "[错误] 未找到 $OUT"
  exit 1
fi

cp ".gh-artifacts/$OUT" "./$OUT"
rm -rf .gh-artifacts

echo ""
echo "========================================"
echo "  完成！可直接发给 Windows 同事"
echo "========================================"
echo ""
echo "  $(pwd)/$OUT"
echo ""
echo "同事用法：解压 → 双击 Clickless.exe（无需 Python）"
echo ""
