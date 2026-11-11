@echo off
chcp 65001 >nul
rem Remote Desktop 서버 실행 (API · WebSocket · 웹 화면을 8000번 포트 하나로 제공)
setlocal EnableExtensions
set "PYTHONUTF8=1"
cd /d "%~dp0"
title Remote Desktop 서버

if not exist ".venv\Scripts\python.exe" (
  echo [오류] 설치가 되어 있지 않습니다. setup.bat 을 먼저 실행하세요.
  pause
  exit /b 1
)
if not exist "web\dist\index.html" (
  echo [안내] 웹 화면이 빌드되지 않았습니다. setup.bat 을 다시 실행하세요.
)

echo ============================================================
echo   Remote Desktop 서버
echo ============================================================
echo   이 컴퓨터에서:          http://localhost:8000
echo   같은 네트워크의 다른 기기에서:
powershell -NoProfile -Command "Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | ForEach-Object { '    http://' + $_.IPv4Address[0].IPAddress + ':8000' }" 2>nul
echo.
echo   호스트 앱^(RemoteDesktopHost.exe^)의 서버 주소에도 위 주소를 입력하세요.
echo   종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo ============================================================
echo.

".venv\Scripts\python.exe" -m uvicorn server.main:app --host 0.0.0.0 --port 8000
echo.
echo 서버가 종료되었습니다.
pause
