# Remote Desktop

Python(FastAPI) + TypeScript + PostgreSQL + Python GUI(tkinter)로 만든 웹 기반 원격 데스크톱입니다.

```
┌──────────────────────┐  WebSocket: JPEG 프레임  ┌──────────────────────────┐  WebSocket: JPEG 프레임  ┌──────────────────────┐
│ 호스트 PC            │ ──────────────────────▶ │ FastAPI 서버 (:8000)     │ ──────────────────────▶ │ 뷰어 (브라우저)       │
│ agent/ (tkinter GUI) │                         │ server/  ·  웹 화면 제공  │                         │ web/ (TypeScript)    │
│ mss 캡처 · pynput 입력│ ◀────────────────────── │            │             │ ◀────────────────────── │ 로그인 · 회원가입     │
└──────────────────────┘     입력 이벤트(즉시)    └────────────┼─────────────┘     마우스 · 키보드 입력   └──────────────────────┘
                                                             ▼
                                                PostgreSQL (users, sessions, viewers)
```

| 구성 | 역할 |
|---|---|
| `server/` Python · FastAPI | 컴퓨터 간 데이터 중계(화면 프레임, 입력 이벤트), DB 저장, JWT 인증, 빌드된 웹 화면 제공 |
| `web/` TypeScript · Vite · zod | 로그인/회원가입, 세션 목록, 원격 화면 뷰어. 미리 정의된 타입만 송수신 |
| `agent/` Python · tkinter | 호스트 PC 앱: 로그인, 세션 생성, 화면 공유, 원격 입력 재생 (Windows용 `.exe` 제공) |
| PostgreSQL | 사용자, 세션, 참여자 (HTTP 호환 모드에서는 최신 프레임과 입력 큐도 저장) |

## 타입 고정 송수신

다음 세 파일에 같은 스키마가 정의되어 있습니다. 하나를 바꾸면 나머지 둘도 함께 바꿔야 합니다.

- `server/schemas.py` (Pydantic, `extra="forbid"`)
- `web/src/protocol.ts` (zod, `.strict()`)
- `agent/protocol.py` (Pydantic)

- 웹 클라이언트는 보내기 전과 받은 뒤 모두 스키마로 검증합니다.
- 서버는 정의되지 않은 필드나 타입(`shell_exec` 등), 범위를 벗어난 값(좌표 0–1 밖 등)을 거부합니다.
- 입력 이벤트는 `mouse_move`, `mouse_down`, `mouse_up`, `wheel`, `key_down`, `key_up` 여섯 종류만 허용됩니다.
- WebSocket에서는 바이너리 메시지는 JPEG 프레임만, 텍스트 메시지는 `auth`, `frame_meta`, `input`, `status`, `error`만 허용됩니다.

## 한 번에 설치하기 (Windows, 추천)

저장소를 받은 폴더에서 **`setup.bat`을 마우스 오른쪽 클릭 → 관리자 권한으로 실행**합니다. 한 번에 아래 과정을 모두 진행합니다.

| 단계 | 내용 |
|---|---|
| 1. Python | 3.11 이상(tkinter 포함)이 없으면 winget으로 Python 3.12 설치 |
| 2. Node.js | 18 이상이 없으면 winget으로 Node.js LTS 설치 |
| 3. PostgreSQL | 없으면 winget으로 PostgreSQL 18 설치(비밀번호 `postgres`, 포트 5432), 서비스 시작 |
| 4. Python 패키지 | `.venv` 가상환경을 만들고 `requirements-dev.txt`와 `agent/requirements.txt` 설치 |
| 5. 데이터베이스 | `remote_desktop` DB 생성. 비밀번호가 `postgres`가 아니면 물어보고(입력은 화면에 표시되지 않음) `.env`에 저장 |
| 6. 웹 | `web/`에서 `npm install`과 `npm run build` 실행 |
| 방화벽 | 관리자 권한으로 실행했다면 8000번 포트 허용 |

설치가 끝나면 **`start_server.bat`을 더블클릭**하면 서버가 시작됩니다. 창에 이 컴퓨터와 다른 기기에서 접속할 주소가 표시됩니다.

- 이미 설치된 것은 건너뛰므로 여러 번 실행해도 됩니다. 코드를 업데이트한 뒤에도 다시 실행하세요.
- winget이 없는 Windows(일부 구형 Windows 10)에서는 Python, Node.js, PostgreSQL을 직접 설치한 뒤 실행하세요.
- 묻지 않고 진행하려면 `setup.bat /y`를 씁니다. 이때 PostgreSQL 비밀번호는 환경 변수 `RD_PG_PASSWORD`로 지정합니다.
- `setup.bat`은 GitHub Actions의 Windows 환경에서 매번 실행해 검증합니다(`.github/workflows/windows-setup.yml`).

## 직접 설치 (서버 컴퓨터, 처음 한 번)

필요한 것: Python 3.11 이상, Node.js 20 이상, PostgreSQL 16 이상(또는 Docker). 아래 명령은 Windows PowerShell 기준입니다.

**1. PostgreSQL 준비**

PostgreSQL을 설치했다면 `remote_desktop` DB를 만듭니다(경로의 `18`은 설치된 버전에 맞게 바꾸세요).

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE remote_desktop;"
```

Docker를 쓴다면 아래 명령 하나로 끝납니다.

```powershell
docker compose up -d
```

기본 접속 정보는 `postgres` / `postgres` @ `localhost:5432` / `remote_desktop`입니다. 다르면 `DATABASE_URL` 환경 변수로 지정합니다(`.env.example` 참고).

**2. Python 패키지 설치**

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\Activate.ps1
```

```powershell
python -m pip install -r requirements-dev.txt -r agent/requirements.txt
```

**3. 웹 화면 빌드** (웹 코드를 바꿨을 때도 다시 실행)

```powershell
cd web; npm install; npm run build; cd ..
```

## 실행

서버 하나가 API, WebSocket, 웹 화면을 모두 제공합니다.

```powershell
.venv\Scripts\Activate.ps1
```

```powershell
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

- 서버 컴퓨터에서는 `http://localhost:8000`, 다른 컴퓨터에서는 `http://<서버 IP>:8000`으로 접속합니다. 서버 IP는 `ipconfig`에서 **기본 게이트웨이가 있는 어댑터**의 IPv4 주소입니다.
- `/api/health/db`에서 DB 연결을 확인할 수 있습니다.
- 다른 컴퓨터에서 접속이 안 되면 서버 컴퓨터의 관리자 PowerShell에서 방화벽을 엽니다.

  ```powershell
  New-NetFirewallRule -DisplayName "Remote Desktop 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private,Domain
  ```
- 실시간 상태가 서버 메모리에 있으므로 워커는 1개(기본값)로 실행하세요. `--workers` 옵션은 쓰지 마세요.
- JWT 서명 키는 처음 실행할 때 `.jwt_secret` 파일에 자동으로 만들어집니다. 이 파일은 git에 올라가지 않습니다. 직접 지정하려면 `JWT_SECRET` 환경 변수를 쓰세요.

### 사용 순서

1. 공유할 컴퓨터에서 호스트 앱(`RemoteDesktopHost.exe` 또는 `python run_host.py`)을 실행합니다. 서버 주소를 입력하고 회원가입이나 로그인을 합니다.
2. **공유 시작**을 누르면 8자리 접속 코드가 표시됩니다.
3. 보는 컴퓨터의 브라우저에서 `http://<서버 IP>:8000`에 접속해 로그인하고, 접속 코드를 입력합니다.
4. 원격 조작이 필요하면 호스트 앱에서 **원격 제어 허용**을 체크합니다. 그다음 브라우저의 화면을 클릭한 뒤 조작합니다.

### 웹 개발 모드 (코드 수정 시)

서버와 함께 Vite 개발 서버를 띄우면 코드를 저장할 때마다 자동으로 반영됩니다. `/api`와 WebSocket 요청은 8000번 포트로 프록시됩니다.

```powershell
cd web; npm run dev -- --host
```

이 경우 `http://<서버 IP>:5173`으로 접속합니다.

### 테스트

테스트는 실제 PostgreSQL을 사용합니다.

```powershell
$env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/remote_desktop_test"; python -m pytest -q
```

테스트 DB는 미리 만들어 두어야 합니다(`CREATE DATABASE remote_desktop_test;`).

## 호스트 앱: Windows용 .exe (Python 설치 불필요)

[Releases](https://github.com/Ryu-Taehyun/Remote-Desktop-TS/releases/latest)에서 `RemoteDesktopHost.exe`를 받아 더블클릭하면 됩니다.

- 마지막으로 로그인한 서버 주소와 이메일을 `%APPDATA%\RemoteDesktopHost\settings.json`에 기억합니다. 비밀번호는 저장하지 않습니다.
- 처음 실행하면 Windows SmartScreen이 "알 수 없는 게시자"라고 경고할 수 있습니다. 코드 서명이 없어서 그렇고, **추가 정보 → 실행**을 누르면 됩니다.
- 빌드는 GitHub Actions(`.github/workflows/build-exe.yml`)가 Windows에서 PyInstaller로 합니다. `main`에 `agent/` 또는 `run_host.py` 변경이 push되면 새 Release(`v1.0.<실행번호>`)가 자동으로 만들어집니다. 원하는 버전명이 있으면 태그를 push하세요.

  ```bash
  git tag v1.2.0 && git push origin v1.2.0
  ```

## 전송 방식과 속도

| 방식 | 언제 | 속도(1280px, 품질 60 기준 측정) |
|---|---|---|
| **실시간 (WebSocket)** | 기본 | 약 56–60 fps (FPS 설정 60). 입력이 즉시 전달됨 |
| **호환 모드 (HTTP 폴링)** | 프록시나 방화벽 때문에 WebSocket이 막힌 경우 자동 전환 | 약 8–10 fps |

현재 방식은 호스트 앱 상태줄과 뷰어 오른쪽 위에 표시됩니다.

- 실시간 모드에서는 프레임이 DB를 거치지 않고 서버 메모리에서 바로 전달됩니다.
- 호스트 앱은 여러 스레드(CPU 코어 수에 맞춰 최대 3개)가 동시에 캡처하고 압축합니다. 축소에는 BOX 필터를 써서 속도와 글자 선명도를 함께 챙깁니다.
- 뷰어가 느리면 중간 프레임을 건너뛰고 항상 최신 화면을 보여 줍니다. 화면이 바뀌지 않으면 압축도 전송도 하지 않고, 1초마다 마지막 화면만 다시 보냅니다.
- FPS는 1–60 사이에서 고를 수 있습니다(기본 30). 60 fps, 1280px 기준 네트워크 사용량은 약 2MB/s입니다.
- 더 빠르게 하려면 호스트 앱에서 **최대 너비**를 1024로, **JPEG 품질**을 40–50으로 낮추세요.

## 호스트 OS별 참고

- **Windows**: 관리자 권한으로 실행된 창에는 입력이 전달되지 않을 수 있습니다.
- **macOS**: 시스템 설정 → 개인정보 보호 및 보안에서 터미널(또는 Python)에 *화면 기록*과 *손쉬운 사용* 권한을 줘야 합니다. Retina 화면에서는 캡처 좌표와 마우스 좌표의 배율이 다를 수 있습니다.
- **Linux**: X11에서 동작합니다. Wayland에서는 mss와 pynput이 제한됩니다.

## 보안 메모

- 비밀번호는 bcrypt로 해시하고, 인증은 JWT(Bearer)를 사용합니다. WebSocket에서도 토큰은 URL이 아닌 첫 메시지로 보냅니다.
- 화면을 볼 수 있는 사람은 세션 소유자와 접속 코드로 참여한 로그인 사용자뿐입니다. 원격 입력은 호스트가 허용했을 때만 전달됩니다.
- 접속 코드가 유출되면 **세션 종료**를 눌러 무효화한 뒤 새 세션을 만드세요.
- 서버는 HTTP(암호화 없음)로 동작하므로 같은 네트워크 안에서 쓰는 것을 전제로 합니다. 인터넷에 공개하려면 HTTPS 리버스 프록시(Caddy, nginx 등)를 앞에 두세요.
- 로그인 시도 횟수 제한(rate limit)은 아직 없습니다.

## 만든 사람

- [@Ryu-Taehyun](https://github.com/Ryu-Taehyun) — 기획·개발
- Claude (Anthropic) — 공동 작업
