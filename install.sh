#!/usr/bin/env bash
# 한 줄 설치 (Mac). Node.js·Homebrew·git이 없어도 됩니다 — Mac 기본 curl만 씁니다.
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/EM-H20/lecture-inbox/main/install.sh)"
# 현재 위치에 lecture-inbox 폴더를 만들고 setup.sh(Homebrew·Node·Python·ffmpeg·whisper-cpp 설치)를 이어서 실행합니다.
# 중간에 실패했다면 같은 위치에서 같은 명령을 다시 실행하면 이어서 진행합니다.
set -euo pipefail

[[ "$(uname)" == "Darwin" ]] || { echo "이 설치 스크립트는 Mac 전용입니다."; exit 1; }
target="$PWD/lecture-inbox"

if [ -f "$target/setup.sh" ]; then
  echo "이미 받은 폴더가 있습니다. 설치를 이어서 진행합니다: $target"
elif [ -e "$target" ] && [ -n "$(ls -A "$target")" ]; then
  echo "이미 다른 내용이 있는 폴더입니다: $target"; exit 1
else
  echo "▶ 프로젝트 내려받는 중: $target"
  mkdir -p "$target"
  curl -fsSL https://github.com/EM-H20/lecture-inbox/archive/refs/heads/main.tar.gz \
    | tar -xz --strip-components=1 -C "$target"
fi

bash "$target/setup.sh"
printf '\n다음에 실행할 때:  cd "%s" && npm run dev\n' "$target"
