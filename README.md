# 강의 서랍

세종대학교 집현캠퍼스 로그인 → 강의 MP4 준비 → 사용자 브라우저에서 로컬 다운로드.

- 프론트엔드: React + Vite, Vercel에 정적 배포
- 백엔드: FastAPI + ffmpeg, OCI VM에서 Docker로 실행
- DB 없음. 학교 비밀번호는 저장하지 않으며, 사용자마다 별도의 학교 쿠키 세션을 메모리에 유지
- 영상은 OCI 임시 공간에만 보관하고 사용자에게 `Content-Disposition: attachment`로 전달
- 파일은 브라우저의 다운로드 폴더에 저장. 웹사이트가 사용자의 임의 폴더에 직접 쓰지는 않음

현재 구현 범위는 로그인·영상 다운로드입니다. Whisper 전사의 실행 위치는 별도 결정이 필요합니다.

## 폴더 구조

```text
lecture-inbox/
├── client/        # React + Vite
├── server/        # FastAPI, 테스트, Python 의존성, Dockerfile
├── scripts/       # 통합 개발 실행·설치
├── deploy/        # Caddy 설정
├── package.json   # npm workspace 및 통합 명령
├── compose.yaml   # OCI 배포
└── vercel.json    # Vercel 배포
```

## 로컬에서 실행

Node.js 22.12 이상(또는 24), Python 3.10 이상, ffmpeg가 필요합니다. Python·Node가 설치된 Mac 기준:

```bash
brew install ffmpeg
npm install
npm run setup
npm run dev
```

모노레포 루트에서 실행하세요. `npm run dev:client`와 `npm run dev:server`로 각각 실행할 수도 있습니다. 화면은 http://127.0.0.1:4317, API는 http://127.0.0.1:4318입니다.
개발 중에는 Vite가 `/api`를 로컬 백엔드로 프록시하므로 환경변수 없이 동작합니다.
종료는 Control+C. `npm run setup`은 프로젝트 안의 `.venv`에만 Python 패키지를 설치합니다.

1. 화면에서 본인의 학번·학교 비밀번호로 로그인합니다.
2. `https://ecampus.sejong.ac.kr/mod/vod/viewer.php?id=...` 형식의 강의 재생 주소를 붙여넣습니다.
3. 파일 이름을 정하고 **영상 준비하기**를 누릅니다.
4. 준비 완료 후 **다운로드**를 누릅니다. 실제 저장 완료 여부는 브라우저 다운로드 목록에서 확인합니다.
5. **목록에서 정리**는 서버 임시 파일만 삭제합니다. 이미 컴퓨터에 받은 파일은 삭제하지 않습니다.

학교 로그인·다운로드는 실제 계정으로 아직 검증하지 않았습니다. 연결이 실패하면 학교 TLS/로그인 변경 여부를 확인해야 합니다. 인증서 검증을 끄거나 비밀번호를 소스에 넣지 마세요.

## OCI 배포

Docker와 Docker Compose가 설치된 OCI VM 및 API용 도메인을 준비합니다. 예: `api.example.com`.
해당 도메인의 DNS A 레코드를 VM의 공인 IP로 연결합니다.

이 프로젝트 폴더를 VM에 복사하고 `.env`를 만드세요:

```dotenv
API_DOMAIN=api.example.com
FRONTEND_ORIGINS=https://your-project.vercel.app
SESSION_TTL_SECONDS=7200
FILE_TTL_SECONDS=1800
```

```bash
docker compose up -d --build
```

- OCI 보안 목록/NSG와 VM 방화벽에서 TCP 80·443을 허용합니다. 8000은 인터넷에 공개하지 않습니다.
- Caddy가 HTTPS 인증서를 발급하고 내부의 FastAPI 컨테이너로 연결합니다.
- 프록시 전달 IP는 Caddy를 신뢰하도록 설정했습니다. 반드시 제공된 Compose의 내부 네트워크 구성으로 실행하세요.
- `https://api.example.com/api/health`에서 `ok: true`, `ffmpeg: true`를 확인합니다.
- 별도 계정 DB나 환경변수의 공용 학교 계정은 사용하지 않습니다. 각 사용자가 화면에서 자신의 계정으로 로그인합니다.
- 서버에는 최대 12개 작업, 사용자 세션당 최대 3개 파일, 동시에 2개 다운로드, 파일당 최대 2GiB 제한이 있습니다. 임시 디스크는 여유 공간을 충분히 확보하세요.
- `downloads_tmp` 볼륨은 임시 영상용입니다. 정상 종료 시 정리하고 비정상 종료 잔여물은 다음 시작 시 정리합니다. `/data`에는 이 서비스 이외의 파일을 넣지 마세요.

## Vercel 배포

Vercel의 **Root Directory**는 모노레포 루트(`.`)로 지정하세요. 루트의 `vercel.json`이 client 워크스페이스를 빌드합니다.

| 항목 | 값 |
| --- | --- |
| Framework Preset | Vite |
| Build Command | `npm run build` |
| Output Directory | `client/dist` |
| 환경변수 | `VITE_API_BASE=https://api.example.com` |

환경변수를 설정한 뒤 배포합니다. `VITE_` 환경변수는 브라우저에 공개되므로 학교 비밀번호나 서버 비밀값을 넣으면 안 됩니다.
배포된 프론트엔드의 정확한 Origin을 OCI의 `FRONTEND_ORIGINS`에 넣고 `docker compose up -d`로 반영하세요.
여러 프론트엔드를 허용할 때는 쉼표로 구분하고 끝에 `/`는 붙이지 않습니다. 임의의 Vercel Preview 전체를 와일드카드로 허용하지 않습니다.

Vercel은 화면만 제공합니다. API 요청과 영상 다운로드는 브라우저에서 OCI로 직접 전송됩니다.
대용량 파일을 Vercel 함수로 프록시하거나 JavaScript Blob으로 메모리에 통째로 담지 않습니다.

공식 배포 참고: [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite), [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/).

## 세션·보관 동작

- 애플리케이션 세션은 기본 2시간, 준비된 파일은 기본 30분 유지됩니다. 학교 세션이 더 먼저 만료될 수 있습니다.
- 학교 비밀번호는 로그인 요청에서만 사용합니다. API 세션 토큰은 브라우저의 해당 탭 `sessionStorage`에, 학교 쿠키는 OCI 메모리에만 있습니다.
- 사용자별 파일 소유권을 확인한 후 60초·1회용 다운로드 링크를 발급합니다. 링크를 공유하지 마세요.
- 로그아웃은 세션과 발급된 링크를 무효화합니다. 진행 중인 서버 작업은 취소하고, 이미 전송 중인 파일은 전송이 끝난 후 정리합니다.
- 서버 재시작 시 로그인과 작업 기록은 사라집니다. 학교 계정으로 다시 로그인해야 합니다.
- DB 없는 단일 API 프로세스용 구현입니다. `uvicorn --workers 1`을 유지하세요. 프로세스 잠금이 같은 저장소의 중복 실행을 막습니다. 여러 OCI 인스턴스로 확장하려면 공유 세션·작업 저장소가 필요합니다.
- 원본 레포의 낮은 TLS 보안 수준 호환 어댑터는 포함하지 않았습니다. 학교와 CDN 모두 정상 인증서 검증을 유지합니다.
- 요약·화자 분리·Whisper 전사는 아직 연결하지 않았습니다.

## 검증

```bash
npm test
npm run build
```

테스트에서는 학교 로그인과 CDN을 모의 처리합니다. 두 사용자 간 격리, 비밀번호 오류 응답 비노출, 로그인 시도 제한, 1회용 링크, 만료/로그아웃 후 접근 차단, 전송 중 정리, 403 Referer 재시도, 불완전 파일 정리를 검증합니다.
실제 학교 로그인/영상, OCI 컨테이너 기동, Vercel 배포, 브라우저에서의 시각·다운로드 검증은 별도로 필요합니다.

## 참고한 코드

- [chuseok22-home-server downloader.py](https://github.com/Chuseok22/chuseok22-home-server/blob/main/apps/sejong/lecture/services/downloader.py): HLS → MP4 무재인코딩 저장 및 Referer 재시도 흐름
- [ecampus_auth.py](https://github.com/Chuseok22/chuseok22-home-server/blob/main/apps/sejong/lecture/services/ecampus_auth.py): 학교 로그인 폼과 로그인 성공 판정
- [course.py](https://github.com/Chuseok22/chuseok22-home-server/blob/main/apps/sejong/lecture/services/course.py): 플레이어 설정의 `sources.src` 추출 방식

위 흐름을 별도의 FastAPI 서비스로 구현했습니다. 원본 Django 서버 전체나 PostgreSQL을 실행하지 않습니다.
