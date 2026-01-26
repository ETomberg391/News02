@echo off
echo ====================================
echo    News02 Startup Script (Windows)
echo ====================================
echo.

REM Check if venv exists
if not exist "venv" (
    echo Virtual environment not found. Creating...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created successfully.
    echo.
) else (
    echo Virtual environment found.
    echo.
)

REM Activate the virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment.
    pause
    exit /b 1
)
echo Virtual environment activated.
echo.

REM Install requirements
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt
if errorlevel 1 (
    echo WARNING: Some dependencies may have failed to install.
    echo Continuing anyway...
)
echo Dependencies installed.
echo.

REM Run the program with any arguments passed to this script
echo Starting News02 servers...
python start_servers.py %*

REM If the program exits, pause to see any errors
if errorlevel 1 (
    echo.
    echo Program exited with an error.
    pause
)
