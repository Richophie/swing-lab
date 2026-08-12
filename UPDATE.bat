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
  echo 이 폴더는 Git 저장소가 아닙니다.
  echo GitHub에서 Richophie/swing-lab 저장소를 clone한 폴더에서 실행하세요.
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
