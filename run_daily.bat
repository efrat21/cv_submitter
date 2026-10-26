@echo off title Job Agent - Daily Routine cd /d "D:\cv_submitter"
call ".venv\Scripts\activate.bat"
python -m job_agent.daily_routine --name "" --email ""
echo.
echo Routine finished. Press any key to close this window.
pause >nul
