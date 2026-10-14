#!/usr/bin/env bash
# install.sh 확인: 새 설치 → 이미 최신 → 바뀐 코드 반영 + 내 자료 보존 → 폴더 안 실행 → git 폴더 거부.
# 실행: bash scripts/check-install.sh  (네트워크·setup.sh 없이 임시 폴더에서만 돈다)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/src/server" "$tmp/work"
cp "$root/install.sh" "$tmp/src/"
echo 'echo SETUP_RAN' > "$tmp/src/setup.sh"
echo v1 > "$tmp/src/server/app.py"
app="$tmp/work/lecture-inbox"
run() { (cd "${1:-$tmp/work}" && LECTURE_INBOX_SRC="$tmp/src" bash "$root/install.sh" 2>&1); }
expect() { [[ "$1" == *"$2"* ]] || { printf 'FAIL: %s\n%s\n' "$3" "$1"; exit 1; }; }

out=$(run); expect "$out" '설치 폴더 만드는 중' '새 설치'; expect "$out" SETUP_RAN 'setup.sh 실행'
mkdir -p "$app/sources/과목" "$app/.venv" && echo mine > "$app/sources/과목/a.md"
out=$(run); expect "$out" '이미 최신' '바뀐 게 없으면 최신'
echo v2 > "$tmp/src/server/app.py"
out=$(run); expect "$out" '바뀐 파일 1개' '변경 감지'
[ "$(cat "$app/server/app.py")" = v2 ] || { echo 'FAIL: 변경 반영'; exit 1; }
[ "$(cat "$app/sources/과목/a.md")" = mine ] || { echo 'FAIL: 내 자료 보존'; exit 1; }
out=$(run "$app"); expect "$out" '이미 최신' '설치 폴더 안에서 실행'
[ ! -e "$app/lecture-inbox" ] || { echo 'FAIL: 폴더 안에 또 설치함'; exit 1; }
mkdir "$app/.git"
if out=$(run); then echo 'FAIL: git 폴더를 덮어씀'; exit 1; fi
expect "$out" 'git pull' 'git 폴더 안내'
echo '✓ install.sh 확인 통과'
