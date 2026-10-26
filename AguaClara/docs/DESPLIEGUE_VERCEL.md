# Publicación en Vercel

Estado: publicado y verificado el 4 de octubre de 2026 en https://aguaclara.vercel.app/. Neon Free conectado; secretos configurados en el servidor.

Proyecto existente: `aguaclara`, dominio `aguaclara.vercel.app`.

## Requisitos

- Acceso autenticado a la cuenta propietaria del proyecto.
- PostgreSQL persistente, por ejemplo Neon en Vercel Marketplace. Verificar plan y condiciones antes de contratar. SQLite queda exclusivamente para ejecución local.
- Variables del proyecto: `DATABASE_URL` (URL PostgreSQL con SSL), `GEMINI_API_KEY`, `LLM_MODEL_NAME=gemini-3.6-flash`, `ALLOW_REMOTE=true`, `ADMIN_TOKEN` (clave aleatoria larga, distinta de Gemini).
- La clave de administrador debe conservarse de forma privada. El panel usa esa clave y no la guarda en el navegador.

## Preparación realizada

- FastAPI como framework y `app/main.py` como entrada; máximo de función 60 segundos.
- Python 3.12 en Vercel; Python 3.11 continúa disponible para la ejecución local.
- Driver psycopg y conexiones PostgreSQL sin pool local persistente.
- Bloqueo de arranque en Vercel si faltan la base persistente o el acceso administrativo.
- `.vercelignore` excluye claves, base local, fotografías de consultas, documentación de pruebas y entornos virtuales.
- Las fotos se reducen en el navegador antes de subir y vuelven a validarse en el servidor.

## Verificación realizada

- 70 pruebas automatizadas aprobadas.
- Análisis real de foto y mensaje contextual con Gemini en Vercel.
- Producción: API activa, panel sin clave devuelve 401, medidas sin confirmar rechazadas.
- Consulta sintética guardada en PostgreSQL y recuperada con foto e historial; datos de prueba retirados al finalizar.
- La clave del panel está en el archivo privado Acceso_Admin_AguaClara.txt, fuera de la carpeta del proyecto y del ZIP.

## Límites actuales

- La cuota de Gemini depende del proyecto de Google.
- El límite de solicitudes por IP vive en memoria de cada instancia; no es un limitador distribuido.
- Preview y producción comparten la base; usar datos sintéticos y retirarlos en las verificaciones.

No publicar solo los archivos HTML: esta versión necesita FastAPI. No usar SQLite en `/tmp`: las consultas y fotos se perderían. No subir `.env` ni `data/`.

El despliegue no aumenta ni restablece la cuota de Gemini. Las pruebas locales y la web publicada comparten la cuota si utilizan la misma clave/proyecto de Google.
