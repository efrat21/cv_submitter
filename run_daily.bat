@echo off
title Job Agent - Daily Preparation
cd /d "D:\cv_submitter"
call ".venv\Scripts\activate.bat"
python -m job_agent.cli.host daily --name "Efrat Miyara" --email "efrat.miyara@gmail.com"
