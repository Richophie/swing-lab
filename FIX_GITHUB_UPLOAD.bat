@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo Swing Lab GitHub First Upload
echo ========================================

where git >nul 2>nul
if errorlevel 1 (
  echo ERROR: Git is not installed.
  echo Install Git for Windows first.
  pause
  exit /b 1
)

if not exist app.py (
  echo ERROR: app.py was not found in this folder.
  echo Put this BAT file inside the Swing Lab project folder.
  pause
  exit /b 1
)

if not exist .git (
  git init
)

git branch -M main

git config user.name >nul 2>nul
if errorlevel 1 git config user.name "Richophie"

git config user.email >nul 2>nul
if errorlevel 1 git config user.email "swing-lab@users.noreply.github.com"

git remote get-url origin >nul 2>nul
if errorlevel 1 (
  git remote add origin https://github.com/Richophie/swing-lab.git
) else (
  git remote set-url origin https://github.com/Richophie/swing-lab.git
)

git add app.py requirements.txt README.md START_WINDOWS.bat UPDATE.bat start_mac_linux.sh static/index.html

git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Initial Swing Lab upload"
) else (
  echo No new files to commit. Continuing to push existing commit...
)

echo.
echo Pushing to GitHub...
git push -u origin main

if errorlevel 1 (
  echo.
  echo ========================================
  echo UPLOAD FAILED
  echo ========================================
  echo Please copy everything above this line and send it to ChatGPT.
  pause
  exit /b 1
)

echo.
echo ========================================
echo UPLOAD SUCCESS
echo Repository:
echo https://github.com/Richophie/swing-lab
echo ========================================
pause
