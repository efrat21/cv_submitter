@echo off
title Job Agent - Daily Review
cd /d "D:\cv_submitter"
set "PYTHONPATH=D:\cv_submitter\src;%PYTHONPATH%"
tasklist /FI "IMAGENAME eq ollama.exe" | find /I "ollama.exe" >nul || (start "" /min ollama serve & timeout /t 8 /nobreak >nul)
call ".venv\Scripts\activate.bat"
python -m job_agent.daily_routine --name "Efrat Miyara" --email "efrat.miyara@gmail.com"
if errorlevel 1 echo Daily job routine failed.
echo.
pause
