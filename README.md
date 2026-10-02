# 강의 서랍

세종대학교 집현캠퍼스 강의를 내려받고, 강의 영상을 이 컴퓨터에서 Whisper로 전사하고, 교안 PDF와 함께 AI 에이전트가 정리할 수 있게 입력을 준비하는 로컬 도구입니다.

- 모든 것이 내 컴퓨터에서 실행됩니다(웹 화면 + Python 서버 + whisper.cpp). 영상을 외부 서버에 올리지 않고 AI API도 호출하지 않습니다.
- 프론트엔드: React + Vite, 백엔드: FastAPI + ffmpeg. DB 없음.
- 학교 강의 받기: 학교 비밀번호는 저장하지 않으며, 사용자마다 별도의 학교 쿠키 세션을 메모리에 유지합니다. 영상은 서버 임시 폴더에서 `Content-Disposition: attachment`로 브라우저에 전달합니다.
- 내 영상 전사: 영상을 올려 전사하고 `sources/강의이름/전사/`에 저장합니다. 올린 영상은 전사 후 지웁니다.

현재 구현 범위는 로그인·교과 과목/강의 목록 조회·영상 다운로드, 그리고 화면(또는 명령줄)에서의 Whisper 전사와 교안 정리 입력 준비입니다.

## 폴더 구조

```text
lecture-inbox/
├── client/        # React + Vite
├── server/        # FastAPI, 전사 파이프라인(server/lecture), 테스트, Python 의존성
├── scripts/       # 통합 개발 실행·설치·e2e
├── setup.sh       # 처음 설치(Mac)
├── 정리-지침.md    # AI 에이전트용 정리 지침
└── package.json   # npm workspace 및 통합 명령
```

## 로컬에서 실행

사용자에 맞는 항목을 펼쳐 보세요.

<details>
<summary><b>비개발자용 — 설치 한 줄로 실행하기 (Mac)</b></summary>

Windows는 지원하지 않습니다(`.venv/bin/python` 경로를 쓰므로 WSL이 필요합니다).

#### 처음 한 번만: 설치 (Node.js + 명령 한 줄)

1. **Node.js 설치** — [nodejs.org](https://nodejs.org)에서 **LTS** 설치 파일(.pkg)을 받아 더블클릭하고 안내대로 진행합니다. 설치 후 터미널(`⌘ + Space` → `터미널` → Enter)에서 `node -v`를 쳐서 `v22.12` 이상이 나오면 됩니다. Homebrew가 이미 있다면 `brew install node`로도 됩니다.
2. **설치 폴더를 둘 위치로 이동** — 예: `cd ~/Documents`
3. **설치 명령**

   ```bash
   npx github:EM-H20/lecture-inbox
   ```

   현재 위치에 `lecture-inbox` 폴더를 만들고 설치까지 이어서 진행합니다(폴더 이름을 바꾸려면 명령 끝에 이름을 붙이세요). 이미 내용이 있는 폴더에는 설치하지 않습니다. 안에서 `setup.sh`가 하는 일은 이렇습니다.
   - Homebrew, Python, ffmpeg, whisper-cpp 중 없는 것만 설치합니다. 시스템에 설치하기 전에는 항상 "설치할까요? (y/N)"로 먼저 묻습니다.
   - 웹 화면 패키지와 Python 환경을 준비하고, `sources/`·`output/`·`models/` 폴더를 만듭니다.
   - Whisper 모델(약 3GB)을 받을지 묻습니다.

   **Homebrew가 없을 때** 설치 중에 이렇게 진행됩니다.
   - `Press RETURN/ENTER to continue`가 나오면 **Enter**를 누릅니다.
   - **Mac 비밀번호**를 묻습니다. 입력해도 화면에 안 보이는 게 정상입니다(관리자 계정이어야 합니다).
   - 개발자 도구 설치 창이 뜨면 **설치**를 누르고 끝날 때까지 기다립니다(몇 분).
   - 끝나면 스크립트가 알아서 이어서 진행합니다. 새 터미널에서도 `brew`를 쓰도록 `~/.zprofile`에 한 줄 추가할지 물어봅니다.

   저장소가 공개되어 있어야 하고(`github:` 주소), 처음 실행에는 몇 분이 걸릴 수 있습니다.

ZIP 파일로 받았다면 압축을 풀고 터미널에서 그 폴더로 이동한 뒤(`cd ` 다음에 폴더를 터미널 창으로 끌어다 놓고 Enter) `bash setup.sh`를 실행하면 같은 설치가 진행됩니다.

#### 실행

```bash
npm run dev
```

브라우저에서 http://127.0.0.1:4317 을 엽니다. 이 명령 하나로 웹 화면(4317)과 Python 백엔드(4318)가 함께 실행됩니다. 종료는 터미널에서 **Control+C**(둘 다 종료됩니다).

처음 설치할 때 `npx`가 알려 준 대로 `cd lecture-inbox`로 들어가서 실행하세요. 다음부터는 설치 없이 이 폴더로 이동한 뒤 `npm run dev`만 하면 됩니다. 전사·교안 정리는 아래 "강의 전사와 교안 정리" 항목을 보세요.

#### 문제 해결

| 증상 | 해결 |
| --- | --- |
| `command not found: npx` / `node` | Node.js를 설치하지 않았거나 설치 후 터미널을 새로 열지 않았습니다. 위 1번을 하고 터미널을 다시 엽니다. |
| `command not found: brew` | 설치 폴더에서 `bash setup.sh`를 다시 실행하세요. 그래도 안 되면 터미널을 닫고 새로 엽니다. |
| `먼저 npm run setup을 실행해 주세요.` | 프로젝트 폴더에서 `bash setup.sh`(또는 `npm run setup`)를 실행합니다. |
| `address already in use` (4317/4318) | 이전 `npm run dev`가 아직 실행 중입니다. 그 터미널에서 Control+C로 끄세요. |
| 화면은 뜨는데 영상 준비가 실패 | http://127.0.0.1:4318/api/health 에서 `"ffmpeg": true`인지 확인합니다. `false`면 `brew install ffmpeg`. |
| 모델을 나중에 받고 싶다 | `npm run lecture -- models` (더 가벼운 모델은 `--size small`) |
| ZIP을 다른 Mac에서 풀었는데 실행이 안 됨 | 그 PC에서 `bash setup.sh`를 다시 실행합니다(`.venv`·`node_modules`·모델은 PC마다 따로 만들어야 합니다). |

#### ZIP을 만들어 배포하는 사람에게

```bash
npm run zip
```

프로젝트 폴더 옆에 `lecture-inbox.zip`이 만들어집니다. 용량이 크거나 PC마다 다르거나 개인 자료인 것은 자동으로 뺍니다: `models/`, `output/`, `sources/`, `node_modules/`, `.venv/`, `.git/`, `.env`, `client/dist/`. 받는 사람은 위 "처음 한 번만: 설치"대로 하면 이 폴더들이 `bash setup.sh`로 만들어집니다.

</details>

<details>
<summary><b>개발자용 — git clone으로 개발하기</b></summary>

필요: Node.js 22.12 이상(또는 24), Python 3.10 이상, ffmpeg, git.

```bash
git clone <저장소 주소> lecture-inbox && cd lecture-inbox
brew install ffmpeg      # Node·Python이 없으면 brew install node python 도 함께
npm install              # client 워크스페이스 의존성
npm run setup            # .venv 생성 + server/requirements-dev.txt 설치
npm run dev              # 웹(4317) + API(4318) 동시 실행
```

| 명령 | 동작 |
| --- | --- |
| `npm run dev` | `scripts/dev.mjs`가 uvicorn(`127.0.0.1:4318`)과 Vite(`127.0.0.1:4317`)를 함께 실행. Control+C로 둘 다 종료 |
| `npm run dev:client` / `npm run dev:server` | 프론트엔드·백엔드를 각각 실행 |
| `npm run setup` | `.venv` 생성 및 Python 의존성 설치 (프로젝트 안에만 설치) |
| `npm test` | 백엔드 `unittest`와 클라이언트 테스트 실행 |
| `npm run e2e` | 임시 폴더에서 웹 + 서버 + **실제 Whisper**를 켜고, 영상을 올려 전사·저장을 확인한 뒤 전사 도중 종료해도 남는 프로세스가 없는지 확인. 모델(`npm run lecture -- models`)과 한국어 음성(`say`)이 필요하고, 켜 둔 `npm run dev`와 겹치지 않게 4417/4418 포트를 씀 |
| `npm run build` / `npm run preview` | 프론트엔드 빌드 / 빌드 결과 미리보기 |

- Vite가 `/api`를 로컬 백엔드로 프록시하므로 개발 중에는 환경변수가 필요 없습니다.
- 모든 구성이 로컬에서 실행됩니다. Docker는 필요 없습니다.
- 선택 설정은 환경변수로 지정합니다(`.env.example` 참고). 예: `WHISPER_MODEL=small npm run dev`. `.env` 파일은 자동으로 읽히지 않습니다.
- 서버 로그는 `npm run dev` 터미널에 출력됩니다. 로그인, 영상 준비·실패, 다운로드 시작을 작업 ID 앞 8자리와 함께 남기며, 학교 비밀번호·학번·다운로드 링크·ffmpeg stderr는 남기지 않습니다. 요청 단위 접근 로그(`--no-access-log`)는 다운로드 링크가 경로에 들어가므로 꺼 두었습니다.
- 로그는 `server/app.py`의 `uvicorn.error` 로거를 사용합니다. 새 로그도 이 로거로 남기면 같은 터미널에 나옵니다.

</details>

## 사용 방법

1. 화면에서 본인의 학번·학교 비밀번호로 로그인합니다.
2. 수강 과목을 선택합니다. 연도·학기 필터로 이전 학기 과목도 조회할 수 있습니다. 연도는 현재 연도부터 2003년까지 목록에서 고릅니다.
3. 강의 목록에서 **영상 준비**를 누릅니다. 한 강의 준비가 끝나야 다음 강의를 준비할 수 있습니다. 과목명·강의명으로 파일 이름을 만듭니다. **강의 주소로 직접 추가**에서는 기존처럼 `https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=...` 주소와 파일 이름을 입력할 수 있습니다.
4. 준비 완료 후 **다운로드**를 누릅니다. 실제 저장 완료 여부는 브라우저 다운로드 목록에서 확인합니다.
5. **목록에서 정리**는 서버 임시 파일만 삭제합니다. 이미 컴퓨터에 받은 파일은 삭제하지 않습니다.

학교 로그인·목록 조회·다운로드는 실제 계정으로 아직 검증하지 않았습니다. 목록은 원본 저장소의 교과 조회 페이지(`/local/ubion/user/index.php`)와 동영상 항목 구조를 기준으로 구현했으며, 비교과 목록 조회는 포함하지 않습니다. 조회 실패·학교 로그인 만료는 빈 목록과 구분해 안내합니다. 학교 세션 만료 안내만으로 준비된 파일을 삭제하지 않으며, 재연결 전 받을 파일은 먼저 다운로드하세요. 연결이 실패하면 학교 TLS/로그인 변경 여부를 확인해야 합니다. 인증서 검증을 끄거나 비밀번호를 소스에 넣지 마세요.

## 강의 전사와 교안 정리 (화면 / 명령줄)

영상·음성 파일을 이 컴퓨터에서 전사하고, 교안 PDF와 함께 AI 에이전트(Claude Code, Codex, Gemini 등)가 정리할 수 있게 입력을 준비합니다. 앱이 요약하지는 않으며 AI API도 호출하지 않습니다.

**화면에서 하기** — `npm run dev`로 켜고 http://127.0.0.1:4317 에서 **내 영상 전사** 탭을 엽니다. ① 강의를 고르거나 이름을 입력해 만들고 ② 교안 PDF를 올리고(선택, 여러 개를 한 번에 고를 수 있고 올린 교안은 목록에서 삭제할 수 있습니다) ③ 주차·차시를 정하고 ④ 영상을 끌어다 놓고 [전사 시작]을 누르면, 진행 상태가 표시되고 끝나면 `sources/강의이름/전사/`에 저장됩니다. 올린 영상은 전사 후 지워집니다. 이미 전사된 회차는 "덮어쓰기"를 체크해야만 다시 전사됩니다. **학교 강의 받기** 탭에서 영상을 받은 뒤 [전사하기]를 눌러 같은 방식으로 전사할 수도 있습니다. 끌 때는 터미널에서 Control+C(실행 중인 전사까지 함께 종료됩니다).

아래 명령줄 방법은 같은 일을 터미널에서 하는 방법입니다.

**폴더 구조** — 아래 폴더는 `bash setup.sh`(또는 `npm run setup`)가 만들어 줍니다. 직접 넣는 것은 교안 PDF(여러 개 가능)뿐이고 나머지는 자동으로 생깁니다.

```text
lecture-inbox/
├── sources/                      ← 에이전트가 읽는 재료 (교안 + 전사체)
│   └── 자료구조/                  ← 강의 이름 (폴더 이름 = --course 값)
│       ├── 교안/                  ← 내가 넣는 교안 PDF (여러 개, 파일 이름이 문서 이름)
│       │   ├── 1주차.pdf
│       │   └── 2주차 실습.pdf
│       ├── pages/                ← 자동 생성: 문서마다 쪽별 이미지·텍스트
│       │   └── 1주차/p001.png, p001.txt …
│       └── 전사/                  ← 자동 생성: 전사체
│           └── week_03_01.md     ← 타임스탬프 포함 전사체
├── output/                       ← 에이전트용 작업 목록과 에이전트가 만든 결과
│   └── 자료구조/
│       ├── 정리-작업.md           ← 자동 생성: 에이전트가 읽는 작업 목록
│       └── notes/
│           └── week_03_01.md     ← 에이전트가 쓰는 정리 노트
└── models/                       ← Whisper 모델 (자동으로 받음)
```

`week_03_01`은 3주차의 1번째 강의입니다. 강의 영상 파일은 어디에 두어도 되고, 전사 명령에 경로를 적어 주면 됩니다. `output/`과 `sources/`는 git에 올라가지 않습니다.

**한 번만 준비** (Mac, Apple Silicon 권장)

```bash
brew install whisper-cpp ffmpeg
npm run setup                          # PDF 처리 라이브러리 포함
npm run lecture -- models              # 기본 large-v3(가장 큰 모델)를 models/에 내려받습니다(수 GB)
```

기본 모델은 가장 정확한 `large-v3`입니다. 더 빠른 작은 모델을 쓰려면 `npm run lecture -- models --size small`로 받고 `WHISPER_MODEL=small npm run lecture -- …`처럼 실행합니다. 선택지는 `tiny`, `base`, `small`, `medium`, `large-v3`입니다.

**전사**

```bash
npm run lecture -- transcribe ~/Downloads/강의.mp4 --course 자료구조 --week 3 --session 1
```

`sources/자료구조/전사/week_03_01.md`(구간마다 시작 시각 `[00:21:05]` 포함)가 생깁니다. `week_03_01`은 3주차의 1번째 강의입니다. 이미 있으면 `--force` 없이는 덮어쓰지 않습니다.

**교안**

`sources/자료구조/교안/`에 PDF를 여러 개 넣고(화면에서는 한 번에 여러 개 선택) `npm run lecture -- prepare --course 자료구조`를 실행하면 `sources/자료구조/pages/<문서이름>/`에 페이지별 이미지와 텍스트가 만들어지고 `output/자료구조/정리-작업.md`가 갱신됩니다. 전사 명령도 교안이 있으면 같은 일을 자동으로 합니다.

**정리** — 이 폴더에서 쓰는 에이전트를 열고 이렇게 말합니다.

> output/자료구조/정리-작업.md대로 정리해줘

에이전트는 `정리-지침.md`를 읽고 `output/자료구조/notes/week_03_01.md`에 노트를 씁니다. `output/`과 `sources/`는 git에 올라가지 않습니다.

## 세션·보관 동작

- 애플리케이션 세션은 기본 2시간, 준비된 파일은 기본 30분 유지됩니다. 학교 세션이 더 먼저 만료될 수 있습니다.
- 학교 비밀번호는 로그인 요청에서만 사용합니다. API 세션 토큰은 브라우저의 해당 탭 `sessionStorage`에, 학교 쿠키는 서버 메모리에만 있습니다.
- 사용자별 파일 소유권을 확인한 후 60초·1회용 다운로드 링크를 발급합니다. 링크를 공유하지 마세요.
- 로그아웃은 세션과 발급된 링크를 무효화합니다. 진행 중인 서버 작업은 취소하고, 이미 전송 중인 파일은 전송이 끝난 후 정리합니다.
- 서버 재시작 시 로그인과 작업 기록은 사라집니다. 학교 계정으로 다시 로그인해야 합니다.
- DB 없는 단일 API 프로세스용 구현입니다. `uvicorn --workers 1`을 유지하세요. 프로세스 잠금이 같은 컴퓨터에서 서버를 두 번 켜는 것을 막습니다.
- 원본 레포의 낮은 TLS 보안 수준 호환 어댑터는 포함하지 않았습니다. 학교와 CDN 모두 정상 인증서 검증을 유지합니다.
- 요약·화자 분리는 하지 않습니다.

## 검증

```bash
npm test        # 백엔드 + 클라이언트 테스트
npm run build   # 프론트엔드 빌드
npm run e2e     # 실제 Whisper까지 포함한 전체 흐름 (모델 필요)
```

테스트에서는 학교 로그인과 CDN을 모의 처리합니다. 과목·강의 HTML 파싱, 필터 검증, 사용자별 목록 세션, 조회 중 로그아웃, 학교 만료 응답, 선택한 강의의 다운로드 작업 연결, 두 사용자 간 격리, 비밀번호 오류 응답 비노출, 로그인 시도 제한, 1회용 링크, 만료/로그아웃 후 접근 차단, 전송 중 정리, 403 Referer 재시도, 불완전 파일 정리를 검증합니다.
모의 API를 연결한 브라우저에서 과목 선택·영상 준비 요청, 과목 변경 시 오래된 응답 무시, 오류 후 재시도, 빈 목록, 모바일·데스크톱 화면을 확인했습니다. 실제 학교 로그인/영상 다운로드는 별도 검증이 필요합니다.

## 참고한 코드

- [chuseok22-home-server downloader.py](https://github.com/Chuseok22/chuseok22-home-server/blob/main/apps/sejong/lecture/services/downloader.py): HLS → MP4 무재인코딩 저장 및 Referer 재시도 흐름
- [ecampus_auth.py](https://github.com/Chuseok22/chuseok22-home-server/blob/main/apps/sejong/lecture/services/ecampus_auth.py): 학교 로그인 폼과 로그인 성공 판정
- [course.py](https://github.com/Chuseok22/chuseok22-home-server/blob/main/apps/sejong/lecture/services/course.py): 교과 과목·동영상 목록 파싱, 목록 페이지의 로그인 만료 판정, 플레이어 설정의 `sources.src` 추출 방식

위 흐름을 별도의 FastAPI 서비스로 구현했습니다. 원본 Django 서버 전체나 PostgreSQL을 실행하지 않습니다.
