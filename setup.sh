#!/usr/bin/env bash
# 강의 서랍 첫 설치 (Mac 전용). 여러 번 실행해도 안전합니다: 이미 된 단계는 건너뜁니다.
#   사용법: 프로젝트 폴더에서  bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

step() { printf '\n▶ %s\n' "$1"; }
ask() { local answer; read -r -p "$1 (y/N) " answer; [[ "$answer" =~ ^[Yy]$ ]]; }

[[ "$(uname)" == "Darwin" ]] || { echo "이 설치 스크립트는 Mac 전용입니다."; exit 1; }

# brew는 설치돼 있어도 PATH에 없을 수 있다(특히 방금 설치한 직후). 이 세션에서 바로 쓸 수 있게 한다.
load_brew() {
  local candidate
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$candidate" ]; then eval "$("$candidate" shellenv)"; return 0; fi
  done
  return 1
}

step "1/5 Homebrew (Mac용 프로그램 설치 도구)"
if command -v brew >/dev/null 2>&1 || load_brew; then
  echo "✓ 이미 설치되어 있습니다."
else
  cat <<'EOF'
Homebrew가 없습니다. 설치하는 동안 이렇게 진행됩니다.
  1) "Press RETURN/ENTER to continue" 가 나오면 Enter
  2) Mac 비밀번호 입력 (입력해도 화면에 안 보이는 게 정상입니다)
  3) 개발자 도구 설치 창이 뜨면 [설치]를 누르고 끝날 때까지 기다립니다 (몇 분 걸립니다)
EOF
  ask "Homebrew를 설치할까요?" || { echo "Homebrew가 있어야 계속할 수 있습니다."; exit 1; }
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  load_brew || { echo "설치 후에도 brew를 찾지 못했습니다. 터미널을 닫고 새로 열어 bash setup.sh를 다시 실행해 주세요."; exit 1; }
  if ! grep -qs 'brew shellenv' "$HOME/.zprofile"; then
    ask "새 터미널에서도 brew를 쓰도록 ~/.zprofile에 한 줄을 추가할까요?" \
      && printf '\neval "$(%s shellenv)"\n' "$(command -v brew)" >> "$HOME/.zprofile"
  fi
fi

step "2/5 필요한 프로그램 (Node.js 22.12 이상, Python 3.10 이상, ffmpeg, whisper-cpp)"
missing=()
node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 12) ? 0 : 1)' 2>/dev/null \
  || missing+=(node)
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null || missing+=(python)
command -v ffmpeg >/dev/null 2>&1 || missing+=(ffmpeg)
command -v whisper-cli >/dev/null 2>&1 || missing+=(whisper-cpp)
if [ "${#missing[@]}" -gt 0 ]; then
  echo "설치가 필요합니다: ${missing[*]}"
  ask "brew로 설치할까요?" || { echo "직접 설치하려면: brew install ${missing[*]}"; exit 1; }
  brew install "${missing[@]}"
else
  echo "✓ 모두 설치되어 있습니다."
fi

step "3/5 프로젝트 설치 (웹 화면 패키지, Python 환경, sources·output·models 폴더)"
npm install
npm run setup

step "4/5 AI 에이전트 (시험 대비 노트 정리에 사용, 하나만 있으면 됩니다)"
export PATH="$HOME/.local/bin:$PATH"  # Claude Code·Antigravity 설치 위치
installed=()
for agent in claude codex agy; do command -v "$agent" >/dev/null 2>&1 && installed+=("$agent"); done
if [ "${#installed[@]}" -gt 0 ]; then
  echo "✓ 이미 설치되어 있습니다: ${installed[*]}"
else
  cat <<'EOF'
노트 정리에 쓸 AI를 고르세요. 각 서비스의 계정(유료 요금제 또는 사용 한도)이 필요합니다.
  1) Claude Code  — Claude Pro/Max 등 Anthropic 계정
  2) Codex        — ChatGPT 유료 요금제 계정
  3) Antigravity  — Google 계정
  Enter) 나중에 설치 (전사는 AI 없이도 됩니다)
EOF
  read -r -p "번호: " choice
  case "$choice" in
    1) install="curl -fsSL https://claude.ai/install.sh | bash"; login="claude auth login" ;;
    2) install="brew install --cask codex"; login="codex login" ;;
    3) install="curl -fsSL https://antigravity.google/cli/install.sh | bash"; login="agy" ;;
    *) install=""; login="" ;;
  esac
  # 실패해도 전사 준비(다음 단계)는 계속한다.
  if [ -n "$install" ] && ! bash -c "set -o pipefail; $install"; then
    echo "설치에 실패했습니다. 나중에 다시 시도하려면: $install"
    login=""
  fi
  if [ -n "$login" ]; then
    if [ "$login" = "agy" ]; then
      echo "로그인: 새 터미널에서 agy 를 실행해 안내대로 Google 계정으로 로그인하세요."
    elif ask "지금 로그인할까요? (브라우저가 열립니다)"; then
      $login || echo "로그인에 실패했습니다. 나중에 다시: $login"
    else
      echo "나중에 로그인하려면: $login"
    fi
  else
    echo "나중에 설치하려면 README의 'AI 에이전트' 항목을 보세요."
  fi
fi

step "5/5 Whisper 모델"
memory_gb=$(( $(sysctl -n hw.memsize) / 1073741824 ))
apple_silicon=$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)  # Rosetta 터미널에서도 정확
if [ "$apple_silicon" != 1 ] || [ "$memory_gb" -lt 16 ]; then
  echo "⚠ 이 Mac(메모리 ${memory_gb}GB, $([ "$apple_silicon" = 1 ] && echo Apple Silicon || echo Intel))은 권장 사양(Apple Silicon, 메모리 16GB 이상)보다 낮습니다."
  echo "  large-v3는 느리거나 메모리가 부족할 수 있습니다. README의 '권장 사양'을 참고하세요."
fi
if ls models/ggml-*.bin 2>/dev/null | grep -qv silero; then
  echo "✓ 모델이 이미 있습니다."
elif ask "가장 정확한 large-v3 모델(약 3GB)을 지금 받을까요?"; then
  npm run --silent lecture -- models
else
  echo "나중에 받으려면: npm run lecture -- models   (더 가벼운 모델은 README 참고)"
fi

printf '\n✅ 준비 끝! 이제 이렇게 실행하세요:  npm run dev\n   (끄기: 터미널에서 Control+C)\n'
