@echo off
cls
echo ================================================================================
echo   INVOICE DATA EXTRACTION SYSTEM
echo ================================================================================
echo.
echo [INFO] Starting Flask server...
echo.
echo ================================================================================
echo   SERVER CONFIGURATION
echo ================================================================================
echo.
echo   - Local URL: http://localhost:8001
echo   - API Endpoint: http://localhost:8001/api/extract
echo   - Health Check: http://localhost:8001/api/health
echo.
echo ================================================================================
echo   EXPOSE PUBLICLY (Optional)
echo ================================================================================
echo.
echo   To make this API accessible from anywhere:
echo   1. Keep THIS terminal running
echo   2. Open a NEW terminal
echo   3. Run: START_NGROK.bat
echo.
echo ================================================================================
echo.

python app_web.py
pause
