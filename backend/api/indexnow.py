"""IndexNow (Bing, Yandex, etc.): el archivo de verificación de la clave.

IndexNow exige servir la clave en `https://<host>/<clave>.txt`. La clave es pública por
diseño (cualquiera puede leerla en ese archivo), así que no es un secreto. El envío de URLs
lo hace `scripts/indexnow_submit.py`.
"""
import os

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "f5312258a496448ba01720b86e3a82f3")

router = APIRouter()


# Ruta fija con el valor de la clave (no `/{name}.txt`, que taparía robots.txt y llms.txt).
@router.get(f"/{INDEXNOW_KEY}.txt", include_in_schema=False)
def indexnow_key_file() -> PlainTextResponse:
    return PlainTextResponse(INDEXNOW_KEY)
