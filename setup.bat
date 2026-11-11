@echo off
chcp 65001 >nul
rem ============================================================
rem  Remote Desktop 설치 스크립트 (Windows)
rem   - Python 3.11+, Node.js, PostgreSQL 이 없으면 winget 으로 설치
rem   - remote_desktop 데이터베이스 생성
rem   - requirements 의 Python 패키지, 웹(npm) 패키지 설치 및 웹 빌드
rem   - (관리자 권한일 때) 방화벽 8000번 포트 허용
rem  사용법: setup.bat        (대화형)
rem          setup.bat /y     (묻지 않고 진행, 비밀번호는 RD_PG_PASSWORD 환경 변수)
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
set "PYTHONUTF8=1"
cd /d "%~dp0"
title Remote Desktop 설치

set "AUTO=0"
if /i "%~1"=="/y" set "AUTO=1"
set "HAS_WINGET=0"
where winget >nul 2>&1 && set "HAS_WINGET=1"
set "IS_ADMIN=0"
net session >nul 2>&1 && set "IS_ADMIN=1"

echo ============================================================
echo   Remote Desktop 설치
echo   (PostgreSQL + Python 패키지 + 웹 패키지를 한 번에 설치합니다)
echo ============================================================
echo.

rem ---------------------------------------------------------- 1. Python
echo [1/6] Python 확인
call :find_python
if not defined PY (
  call :winget_install Python.Python.3.12 "Python 3.12"
  call :refresh_path
  call :find_python
)
if not defined PY (
  echo   [오류] Python 3.11 이상^(tkinter 포함^)을 찾을 수 없습니다.
  echo          https://www.python.org/downloads/ 에서 설치한 뒤 이 창을 닫고 다시 실행하세요.
  goto :fail
)
echo   사용: !PY!
echo.

rem ---------------------------------------------------------- 2. Node.js
echo [2/6] Node.js 확인
call :find_node
if not defined HAS_NODE (
  call :winget_install OpenJS.NodeJS.LTS "Node.js LTS"
  call :refresh_path
  call :find_node
)
if not defined HAS_NODE (
  echo   [오류] Node.js 18 이상을 찾을 수 없습니다. https://nodejs.org 에서 LTS 를 설치한 뒤 다시 실행하세요.
  goto :fail
)
for /f "delims=" %%V in ('node --version') do echo   사용: Node.js %%V
echo.

rem ---------------------------------------------------------- 3. PostgreSQL
echo [3/6] PostgreSQL 확인
call :find_pg
if not defined PGBIN (
  if "!HAS_WINGET!"=="0" (
    echo   [오류] PostgreSQL 이 없고 winget 도 없어 자동 설치할 수 없습니다.
    echo          https://www.postgresql.org/download/windows/ 에서 설치하세요. 비밀번호는 postgres 로 정하면 편합니다.
    goto :fail
  )
  echo   PostgreSQL 18 을 설치합니다. 관리자 권한 요청이 뜨면 "예"를 누르세요.
  echo   ^(postgres 계정 비밀번호는 postgres, 포트는 5432 로 설정됩니다^)
  winget install -e --id PostgreSQL.PostgreSQL.18 --accept-package-agreements --accept-source-agreements --custom "--superpassword postgres --serverport 5432"
  call :find_pg
)
if not defined PGBIN (
  echo   [오류] PostgreSQL 설치를 확인할 수 없습니다. 설치가 끝났다면 이 창을 닫고 다시 실행하세요.
  goto :fail
)
echo   사용: !PGBIN!
rem 서비스가 멈춰 있으면 (사용 안 함이면 자동 시작으로 바꾼 뒤) 시작 - 관리자 권한 필요
powershell -NoProfile -Command "$ok = $true; Get-Service postgresql* -ErrorAction SilentlyContinue | ForEach-Object { if ($_.Status -ne 'Running') { try { if ($_.StartType -eq 'Disabled') { Set-Service $_.Name -StartupType Automatic -ErrorAction Stop }; Start-Service $_.Name -ErrorAction Stop; Write-Host ('  service started: ' + $_.Name) } catch { $ok = $false; Write-Host ('  service not started: ' + $_.Name) } } else { Write-Host ('  service running: ' + $_.Name) } }; if (-not $ok) { exit 1 }"
if errorlevel 1 (
  echo   [안내] PostgreSQL 서비스를 시작하지 못했습니다. setup.bat 을 "관리자 권한으로 실행" 하거나,
  echo          services.msc 에서 postgresql-x64-... 서비스를 "자동" 으로 바꾸고 시작하세요.
)
echo.

rem ---------------------------------------------------------- 4. Python 패키지
echo [4/6] Python 가상환경과 패키지 설치 ^(requirements-dev.txt, agent\requirements.txt^)
if not exist ".venv\Scripts\python.exe" (
  !PY! -m venv .venv
  if errorlevel 1 (
    echo   [오류] 가상환경^(.venv^)을 만들지 못했습니다.
    goto :fail
  )
)
set "VPY=%CD%\.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q
"%VPY%" -m pip install -r requirements-dev.txt -r agent\requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo   [오류] Python 패키지 설치에 실패했습니다. 위의 ERROR 메시지를 확인하세요.
  goto :fail
)
echo.

rem ---------------------------------------------------------- 5. 데이터베이스
echo [5/6] 데이터베이스 준비
if "!AUTO!"=="1" (
  "%VPY%" scripts\setup_db.py --yes
) else (
  "%VPY%" scripts\setup_db.py
)
if errorlevel 1 goto :fail
echo.

rem ---------------------------------------------------------- 6. 웹
echo [6/6] 웹 패키지 설치와 빌드 ^(web\^)
pushd web
call npm install --no-fund --no-audit
if errorlevel 1 (
  popd
  echo   [오류] npm install 에 실패했습니다.
  goto :fail
)
call npm run build
if errorlevel 1 (
  popd
  echo   [오류] 웹 빌드에 실패했습니다.
  goto :fail
)
popd
echo.

rem ---------------------------------------------------------- 방화벽
if "!IS_ADMIN!"=="1" (
  netsh advfirewall firewall show rule name="Remote Desktop 8000" >nul 2>&1
  if errorlevel 1 (
    netsh advfirewall firewall add rule name="Remote Desktop 8000" dir=in action=allow protocol=TCP localport=8000 profile=private,domain >nul
    echo   방화벽: 8000번 포트를 허용했습니다 ^(개인/도메인 네트워크^)
  ) else (
    echo   방화벽: 8000번 포트 규칙이 이미 있습니다
  )
) else (
  echo   [안내] 다른 컴퓨터에서 접속하려면 setup.bat 을 마우스 오른쪽 클릭 → "관리자 권한으로 실행" 하면
  echo          방화벽 8000번 포트도 자동으로 열립니다.
)

echo.
echo ============================================================
echo   설치 완료.  start_server.bat 을 더블클릭하면 서버가 시작됩니다.
echo ============================================================
if "!AUTO!"=="0" pause
exit /b 0

:fail
echo.
echo ============================================================
echo   설치가 중단되었습니다. 위의 [오류] 메시지를 확인하세요.
echo ============================================================
if "!AUTO!"=="0" pause
exit /b 1

rem ============================================================ 함수
:find_python
set "PY="
call :try_py py -3
call :try_py python
call :try_py "%LocalAppData%\Programs\Python\Python313\python.exe"
call :try_py "%LocalAppData%\Programs\Python\Python312\python.exe"
call :try_py "%ProgramFiles%\Python313\python.exe"
call :try_py "%ProgramFiles%\Python312\python.exe"
exit /b 0

:try_py
if defined PY exit /b 0
%* -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=%*"
exit /b 0

:find_node
set "HAS_NODE="
where npm >nul 2>&1 || exit /b 0
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" >nul 2>&1 && set "HAS_NODE=1"
exit /b 0

:find_pg
set "PGBIN="
for /d %%D in ("%ProgramFiles%\PostgreSQL\*") do (
  if exist "%%~D\bin\psql.exe" set "PGBIN=%%~D\bin"
)
exit /b 0

:winget_install
if "!HAS_WINGET!"=="0" (
  echo   [안내] winget 이 없어 %~2 을^(를^) 자동 설치할 수 없습니다.
  exit /b 1
)
echo   %~2 설치 중... 설치 창이나 권한 요청이 뜨면 허용하세요.
winget install -e --id %~1 --accept-package-agreements --accept-source-agreements
exit /b 0

:refresh_path
rem winget 으로 설치한 프로그램을 이 창에서 바로 쓸 수 있도록 PATH 다시 읽기
set "SYS_PATH="
set "USR_PATH="
for /f "tokens=2,*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul ^| findstr /i "REG_"') do set "SYS_PATH=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul ^| findstr /i "REG_"') do set "USR_PATH=%%B"
call set "PATH=%SYS_PATH%;%USR_PATH%"
exit /b 0
