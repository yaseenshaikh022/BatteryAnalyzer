@echo off
setlocal
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Starting Battery Analyzer...
python main.py
pause
