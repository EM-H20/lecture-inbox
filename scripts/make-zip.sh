#!/usr/bin/env bash
# 배포용 ZIP을 프로젝트 폴더 옆에 만듭니다. 모델·개인 강의 파일·비밀값·설치 산출물은 넣지 않습니다.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
name="$(basename "$root")"
out="$(dirname "$root")/$name.zip"
rm -f "$out"
cd "$(dirname "$root")"
zip -rq "$out" "$name" -x \
  "$name/models/*" "$name/output/*" "$name/sources/*" \
  "$name/node_modules/*" "$name/client/node_modules/*" "$name/.venv/*" "$name/client/dist/*" \
  "$name/.git/*" "$name/.env" "$name/.superpowers/*" "$name/.playwright-mcp/*" "$name/docs/superpowers/*" \
  "*__pycache__*" "*.DS_Store"
echo "만들었습니다: $out ($(du -h "$out" | cut -f1))"
