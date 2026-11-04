"""Envía a IndexNow todas las URLs del sitemap de producción.

Uso:  python scripts/indexnow_submit.py            # envía
      python scripts/indexnow_submit.py --dry-run  # solo cuenta las URLs

Requisito: que `https://<host>/<clave>.txt` ya esté desplegado (IndexNow lo verifica).
"""
import json
import os
import re
import sys
import urllib.request

HOST = os.environ.get("CANONICAL_HOST", "evemarket-analyzer.online")
KEY = os.environ.get("INDEXNOW_KEY", "f5312258a496448ba01720b86e3a82f3")
ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 10000  # límite del protocolo por petición
UA = "EveMarketIndexNow/1.0"  # Cloudflare rechaza el User-Agent por defecto de urllib


def sitemap_urls() -> list[str]:
    req = urllib.request.Request(f"https://{HOST}/sitemap.xml", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml = resp.read().decode("utf-8")
    return list(dict.fromkeys(re.findall(r"<loc>([^<]+)</loc>", xml)))


def submit(urls: list[str]) -> int:
    payload = {
        "host": HOST,
        "key": KEY,
        "keyLocation": f"https://{HOST}/{KEY}.txt",
        "urlList": urls,
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status


def main() -> None:
    urls = sitemap_urls()
    print(f"{len(urls)} URLs en el sitemap")
    if "--dry-run" in sys.argv:
        return
    for i in range(0, len(urls), BATCH):
        print("HTTP", submit(urls[i:i + BATCH]))


if __name__ == "__main__":
    main()
