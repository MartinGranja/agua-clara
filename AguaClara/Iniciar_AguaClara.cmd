@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 goto error
)
if not exist ".venv\instalado.txt" (
  .venv\Scripts\python.exe -m pip install -r requirements.lock.txt
  if errorlevel 1 goto error
  echo listo> .venv\instalado.txt
)
if not exist ".env" copy .env.example .env >nul
.venv\Scripts\python.exe run.py
if errorlevel 1 goto error
exit /b
:error
echo No se pudo iniciar. Verifica Python 3.11, la conexion y el mensaje anterior.
pause
