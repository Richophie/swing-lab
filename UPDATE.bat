@echo off
chcp 65001 >nul
cd /d %~dp0

where git >nul 2>nul
if errorlevel 1 (
  echo Git이 설치되어 있지 않습니다.
  pause
  exit /b
)

if not exist .git (
  echo 아직 GitHub 저장소와 연결되지 않았습니다.
  echo 먼저 GITHUB_FIRST_UPLOAD.bat 을 한 번 실행하세요.
  pause
  exit /b
)

echo 최신 버전을 확인합니다...
git pull --ff-only origin main

if errorlevel 1 (
  echo 업데이트 중 충돌 또는 로그인 문제가 발생했습니다.
  pause
  exit /b
)

python -m pip install -r requirements.txt
echo.
echo 업데이트 완료.
pause
