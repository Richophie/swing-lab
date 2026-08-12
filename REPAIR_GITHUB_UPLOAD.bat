@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo Swing Lab GitHub Repair Upload
echo ========================================

where git >nul 2>nul
if errorlevel 1 (
  echo ERROR: Git is not installed.
  pause
  exit /b 1
)

if not exist app.py (
  echo ERROR: app.py was not found in this folder.
  pause
  exit /b 1
)

if exist .git (
  echo Removing broken local Git metadata...
  rmdir /s /q .git
)

git init
git branch -M main

git config user.name "Richophie"
git config user.email "swing-lab@users.noreply.github.com"

git remote add origin https://github.com/Richophie/swing-lab.git

git add .
git commit -m "Initial Swing Lab upload"

if errorlevel 1 (
  echo.
  echo ERROR: Commit failed.
  pause
  exit /b 1
)

echo.
echo Force uploading clean main branch...
git push -u origin main --force

if errorlevel 1 (
  echo.
  echo ========================================
  echo UPLOAD FAILED
  echo ========================================
  echo Copy the lines above and send them to ChatGPT.
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
