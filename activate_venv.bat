@echo off
echo Activating virtual environment...
call .venv\Scripts\activate.bat
echo.
echo Virtual environment activated!
echo Python location: 
where python
echo.
echo To run the dashboard:
echo   python dashboard/app.py
echo.
echo To start Jupyter:
echo   jupyter notebook
echo.
