"""Inicio del servidor y apertura del navegador cuando responde."""
import threading
import time
import urllib.request
import webbrowser
import json
import uvicorn

def open_when_ready():
    for _ in range(40):
        try:
            urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=1).close()
            webbrowser.open('http://127.0.0.1:8766/')
            return
        except OSError:
            time.sleep(.5)

if __name__ == '__main__':
    try:
        with urllib.request.urlopen('http://127.0.0.1:8766/api/config', timeout=2) as response:
            running = json.load(response)
        if 'visionAvailable' in running and 'states' in running:
            print('Agua Clara ya esta funcionando. Abriendo el navegador.')
            print('Si cambiaste .env, detene el servidor anterior con Ctrl+C y volve a iniciar.')
            webbrowser.open('http://127.0.0.1:8766/')
            raise SystemExit(0)
    except (OSError, ValueError):
        pass
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run('app.main:app', host='127.0.0.1', port=8766, use_colors=False)
