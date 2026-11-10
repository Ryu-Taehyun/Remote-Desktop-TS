# Remote Desktop

Python(FastAPI) + TypeScript + PostgreSQL + Python GUI(tkinter)로 만든 웹 기반 원격 데스크톱입니다. Vercel에 배포할 수 있습니다.

```
┌──────────────────────┐   PUT /frame (JPEG)    ┌──────────────────────┐   GET /frame?after=seq  ┌──────────────────────┐
│ 호스트 PC            │ ─────────────────────▶ │ FastAPI (Vercel 함수) │ ◀────────────────────── │ 뷰어 (브라우저)       │
│ agent/ (tkinter GUI) │                        │ server/               │                         │ web/ (TypeScript)    │
│ mss 캡처 · pynput 입력│ ◀───────────────────── │        │              │ ─────────────────────▶ │ 로그인 · 회원가입     │
└──────────────────────┘   GET /input (드레인)   └────────┼──────────────┘   POST /input (배치)     └──────────────────────┘
                                                          ▼
                                                 PostgreSQL (users, sessions, frames, input_events)
```

| 구성 | 역할 |
|---|---|
| `server/` Python · FastAPI | 컴퓨터 간 데이터 중계(화면 프레임, 입력 이벤트), DB 저장, JWT 인증 |
| `web/` TypeScript · Vite · zod | 로그인/회원가입, 세션 목록, 원격 화면 뷰어. 미리 정의된 타입만 송수신 |
| `agent/` Python · tkinter | 호스트 PC 앱: 로그인, 세션 생성, 화면 공유, 원격 입력 재생 |
| PostgreSQL | 사용자, 세션, 최신 프레임, 입력 큐 |

## 타입 고정 송수신

다음 세 파일에 같은 스키마가 정의되어 있습니다. 하나를 바꾸면 나머지 둘도 함께 바꿔야 합니다.

- `server/schemas.py` (Pydantic, `extra="forbid"`)
- `web/src/protocol.ts` (zod, `.strict()`)
- `agent/protocol.py` (Pydantic)

웹 클라이언트(`web/src/api.ts`)는 **보내기 전에** 요청 본문을, **받은 뒤에** 응답 본문을 스키마로 검증합니다. 서버는 정의되지 않은 필드, 타입(`shell_exec` 등), 범위를 벗어난 값(좌표 0–1 밖 등)을 422로 거부합니다. 입력 이벤트는 `mouse_move`, `mouse_down`, `mouse_up`, `wheel`, `key_down`, `key_up` 여섯 종류만 허용됩니다.

## 로컬 실행

필요한 것: Python 3.11 이상(tkinter 포함), Node 20 이상, PostgreSQL 16(또는 Docker).

```bash
docker compose up -d
```

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
```

```bash
cp .env.example .env && export $(grep -v '^#' .env | xargs)
```

```bash
uvicorn server.main:app --reload --port 8000
```

다른 터미널에서 웹을 실행합니다(`/api`는 8000번 포트로 프록시됩니다).

```bash
cd web && npm install && npm run dev
```

호스트 PC에서 GUI 앱을 실행합니다.

```bash
pip install -r agent/requirements.txt
```

```bash
python -m agent
```

사용 순서:
1. 호스트 앱에서 서버 주소(`http://localhost:8000` 또는 Vercel URL)를 입력하고 회원가입 또는 로그인합니다.
2. **공유 시작**을 누르면 8자리 접속 코드가 표시됩니다.
3. 브라우저(`http://localhost:5173`)에서 다른 계정으로 로그인한 뒤 접속 코드로 참여합니다.
4. 원격 조작이 필요하면 호스트 앱에서 **원격 제어 허용**을 체크합니다(웹의 세션 소유자 화면에서도 바꿀 수 있습니다).

테스트(실제 PostgreSQL 사용):

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/remote_desktop_test pytest -q
```

## 빠른 실행: Windows용 .exe (Python 설치 불필요)

[Releases](https://github.com/Ryu-Taehyun/Remote-Desktop-TS/releases/latest)에서 `RemoteDesktopHost.exe`를 받아 더블클릭하면 호스트 앱이 실행됩니다.

- 마지막으로 로그인한 서버 주소와 이메일을 `%APPDATA%\RemoteDesktopHost\settings.json`에 기억합니다. 비밀번호는 저장하지 않습니다.
- 처음 실행하면 Windows SmartScreen이 "알 수 없는 게시자"라고 경고할 수 있습니다. 코드 서명이 없어서 그렇고, **추가 정보 → 실행**을 누르면 됩니다.
- 빌드는 GitHub Actions(`.github/workflows/build-exe.yml`)가 Windows에서 PyInstaller로 합니다. `main`에 `agent/` 또는 `run_host.py` 변경이 push되면 자동으로 새 Release(`v1.0.<실행번호>`)가 만들어집니다. 원하는 버전명이 있으면 태그를 push하세요.

  ```bash
  git tag v1.2.0 && git push origin v1.2.0
  ```

소스에서 바로 실행하려면:

```bash
python run_host.py
```

## Vercel 배포

1. 이 폴더를 GitHub 저장소로 push한 뒤 Vercel에서 Import합니다. 설정은 `vercel.json`에 모두 들어 있어서 Framework Preset 등은 바꾸지 않아도 됩니다.
   - 웹: `web/`에서 `npm ci && npm run build` → `web/dist` 정적 배포
   - API: `api/index.py`(Python 서버리스 함수) ← `/api/*` 전체 rewrite, `server/` 패키지 포함
2. **Storage → Neon(Postgres)** 을 연결하면 `POSTGRES_URL`이 자동으로 주입됩니다. 외부 DB를 쓴다면 `DATABASE_URL`을 직접 설정합니다(`?sslmode=require` 포함).
3. 환경 변수 `JWT_SECRET`에 긴 랜덤 문자열을 설정합니다. 설정하지 않으면 배포된 함수가 시작되지 않도록 막아 두었습니다.

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
4. 테이블은 첫 요청 때 자동으로 생성됩니다. 직접 만들고 싶다면 `db/schema.sql`을 실행합니다.
5. 호스트 앱의 서버 주소에 `https://<프로젝트>.vercel.app`을 입력합니다.

CLI로 배포하려면:

```bash
npx vercel --prod
```

### Vercel 환경의 제약 (중요)

- **WebSocket 없음**: Vercel 서버리스 함수는 연결을 유지할 수 없어서 HTTP 폴링으로 구현했습니다. 지연은 수백 ms 수준이고, 실용적인 속도는 2–5 fps입니다(GUI에서 FPS·품질·해상도를 조절할 수 있습니다).
- **요청 수와 비용**: 4 fps로 공유하면 호스트와 뷰어를 합쳐 초당 약 10건의 함수 호출이 발생합니다. Hobby 플랜 한도를 금방 넘길 수 있으니 사용하지 않을 때는 공유를 중지하세요. 프레임이 DB를 거치므로 Neon 사용량도 늘어납니다.
- **본문 크기 4.5MB 제한**: 프레임 하나는 서버에서 3MB로 제한됩니다(1280px, 품질 60 기준 약 30–150KB).
- 실시간 성능이 필요하다면 같은 `server/` 코드를 Railway, Fly.io, VM 등 상시 실행 환경에서 `uvicorn`으로 띄우면 됩니다. 이 경우 WebSocket으로 바꿀 수도 있습니다.

## 호스트 OS별 참고

- **macOS**: 시스템 설정 → 개인정보 보호 및 보안에서 터미널(또는 Python)에 *화면 기록*과 *손쉬운 사용* 권한을 줘야 합니다. Retina 화면에서는 캡처 좌표(픽셀)와 마우스 좌표(포인트)의 배율이 다를 수 있습니다.
- **Linux**: X11에서 동작합니다. Wayland에서는 mss와 pynput이 제한됩니다.
- **Windows**: 관리자 권한 창에는 입력이 전달되지 않을 수 있습니다.

## 보안 메모

- 비밀번호는 bcrypt로 해시하고, 인증은 JWT(Bearer)를 사용합니다.
- 화면을 볼 수 있는 사람은 세션 소유자와 접속 코드로 참여한 로그인 사용자뿐입니다. 원격 입력은 호스트가 허용했을 때만 전달되고 재생됩니다.
- 접속 코드가 유출되면 **세션 종료**를 눌러 무효화한 뒤 새 세션을 만드세요.
- 로그인 시도 횟수 제한(rate limit)은 아직 없습니다. 공개 배포 전에 추가하는 것을 권장합니다.
