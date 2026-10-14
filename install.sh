#!/usr/bin/env bash
# 한 줄 설치·업데이트 (Mac). Node.js·Homebrew·git이 없어도 됩니다 — Mac 기본 curl만 씁니다.
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/EM-H20/lecture-inbox/main/install.sh)"
# 현재 위치에 lecture-inbox 폴더를 만들고 setup.sh(Homebrew·Node·Python·ffmpeg·whisper-cpp 설치)를 이어서 실행합니다.
# 이미 설치한 위치에서 다시 실행하면 바뀐 코드만 덮어쓰고(sources·output·models 등 내 자료는 그대로) setup.sh로 마무리합니다.
# 중간에 실패했다면 같은 위치에서 같은 명령을 다시 실행하면 이어서 진행합니다.
set -euo pipefail

[[ "$(uname)" == "Darwin" ]] || { echo "이 설치 스크립트는 Mac 전용입니다."; exit 1; }
target="${LECTURE_INBOX_DIR:-$PWD/lecture-inbox}"  # npx 설치(scripts/install.mjs)가 폴더 이름을 넘길 때 씀
# 설치 폴더 안에서 실행했다면 그 폴더를 업데이트한다(안에 또 하나 만들지 않도록).
[ -z "${LECTURE_INBOX_DIR:-}" ] && [ -f "$PWD/setup.sh" ] && [ -f "$PWD/install.sh" ] && target="$PWD"

if [ -e "$target/.git" ]; then
  echo "git으로 받은 폴더입니다. 덮어쓰지 않습니다. 업데이트는 그 폴더에서 git pull 로 하세요: $target"; exit 1
elif [ -e "$target" ] && [ ! -f "$target/setup.sh" ] && [ -n "$(ls -A "$target")" ]; then
  echo "이미 다른 내용이 있는 폴더입니다: $target"; exit 1
fi

src="${LECTURE_INBOX_SRC:-}"  # npx 설치는 이미 받은 코드를 넘긴다
if [ -z "$src" ]; then
  echo "▶ 최신 코드 내려받는 중"
  src="$(mktemp -d)"
  trap 'rm -rf "$src"' EXIT
  curl -fsSL https://github.com/EM-H20/lecture-inbox/archive/refs/heads/main.tar.gz \
    | tar -xz --strip-components=1 -C "$src"
fi

if [ -f "$target/setup.sh" ]; then
  # 내 폴더에만 있는 것(sources·output·models·.venv 등)은 비교·삭제 대상이 아니다.
  changed=$(diff -rq "$src" "$target" 2>/dev/null | grep -cvF "Only in $target" || true)
  if [ "$changed" -eq 0 ]; then
    echo "✓ 이미 최신 버전입니다. 설치 상태만 확인합니다: $target"
  else
    echo "▶ 새 버전으로 업데이트합니다 (바뀐 파일 ${changed}개, 내 강의 자료·노트·모델은 그대로 둡니다): $target"
    cp -R "$src/." "$target/"
  fi
else
  echo "▶ 설치 폴더 만드는 중: $target"
  mkdir -p "$target"
  cp -R "$src/." "$target/"
fi

bash "$target/setup.sh"
printf '\n다음에 실행할 때:  cd "%s" && npm run dev\n' "$target"
printf '업데이트할 때:  이 폴더가 있는 위치에서 설치 명령을 그대로 다시 실행 (켜 둔 npm run dev는 껐다 켜세요)\n'
