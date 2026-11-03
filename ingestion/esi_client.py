import time

import httpx

DEFAULT_BASE_URL = "https://esi.evetech.net/latest"


class EsiClient:
    """Cliente HTTP para la EVE Swagger Interface (ESI).

    Respeta el rate limit de error de la ESI (X-Esi-Error-Limit-Remain) y reintenta
    ante 5xx/timeouts con backoff exponencial. No requiere autenticación para los
    endpoints públicos de mercado usados en este proyecto.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, user_agent: str = "eve-market-screener",
                 max_retries: int = 5, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _get(self, path: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            response = self._client.get(url, params=params, headers=headers)

            remain = response.headers.get("X-Esi-Error-Limit-Remain")
            reset = response.headers.get("X-Esi-Error-Limit-Reset")
            if remain is not None and int(remain) <= 2 and reset is not None:
                time.sleep(int(reset))

            if response.status_code == 420:
                retry_after = int(response.headers.get("Retry-After", reset or 60))
                time.sleep(retry_after)
                if attempt <= self.max_retries:
                    continue
                response.raise_for_status()

            if response.status_code >= 500 and attempt <= self.max_retries:
                time.sleep(min(2 ** attempt, 30))
                continue

            response.raise_for_status()
            return response

    def get_active_type_ids(self, region_id: int) -> list[int]:
        """GET /markets/{region_id}/types/ — tipos con órdenes activas en la región."""
        type_ids: list[int] = []
        page = 1
        while True:
            response = self._get(f"/markets/{region_id}/types/", params={"page": page})
            type_ids.extend(response.json())
            total_pages = int(response.headers.get("X-Pages", 1))
            if page >= total_pages:
                break
            page += 1
        return type_ids

    def get_orders(self, region_id: int, order_type: str = "all", type_id: int | None = None) -> list[dict]:
        """GET /markets/{region_id}/orders/ — órdenes activas (paginado).

        Con `type_id`, la ESI filtra server-side a un solo ítem: se usa para traer el
        libro de órdenes real de un ítem puntual (motor de posiciones) sin descargar
        la región entera, que es lo que hace la llamada sin `type_id` (motor de mercado)."""
        orders: list[dict] = []
        page = 1
        while True:
            params = {"order_type": order_type, "page": page}
            if type_id is not None:
                params["type_id"] = type_id
            response = self._get(f"/markets/{region_id}/orders/", params=params)
            orders.extend(response.json())
            total_pages = int(response.headers.get("X-Pages", 1))
            if page >= total_pages:
                break
            page += 1
        return orders

    def get_history(self, region_id: int, type_id: int) -> list[dict]:
        """GET /markets/{region_id}/history/?type_id= — histórico diario (hasta ~1 año)."""
        response = self._get(f"/markets/{region_id}/history/", params={"type_id": type_id})
        return response.json()

    def get_type_name(self, type_id: int) -> str:
        """GET /universe/types/{type_id}/ — nombre legible del ítem."""
        response = self._get(f"/universe/types/{type_id}/")
        return response.json()["name"]

    def _post(self, path: str, json: dict | list | None = None, params: dict | None = None,
              headers: dict | None = None) -> httpx.Response:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            response = self._client.post(url, json=json, params=params, headers=headers)
            if response.status_code == 420:
                retry_after = int(response.headers.get("Retry-After", 60))
                time.sleep(retry_after)
                if attempt <= self.max_retries:
                    continue
            if response.status_code >= 500 and attempt <= self.max_retries:
                time.sleep(min(2 ** attempt, 30))
                continue
            response.raise_for_status()
            return response

    def get_type_names_bulk(self, type_ids: list[int]) -> dict[int, str]:
        """POST /universe/names/ — resuelve nombres en lotes de hasta 1000 ids."""
        names: dict[int, str] = {}
        for i in range(0, len(type_ids), 1000):
            batch = type_ids[i:i + 1000]
            response = self._post("/universe/names/", json=batch)
            for entry in response.json():
                names[entry["id"]] = entry["name"]
        return names

    def get_type_group_id(self, type_id: int) -> int:
        """GET /universe/types/{type_id}/ — group_id del ítem (no hay endpoint bulk para esto)."""
        response = self._get(f"/universe/types/{type_id}/")
        return response.json()["group_id"]

    def get_group(self, group_id: int) -> dict:
        """GET /universe/groups/{group_id}/ — nombre del grupo y category_id."""
        response = self._get(f"/universe/groups/{group_id}/")
        data = response.json()
        return {"name": data["name"], "category_id": data["category_id"]}

    def get_category_name(self, category_id: int) -> str:
        """GET /universe/categories/{category_id}/ — nombre de la categoría."""
        response = self._get(f"/universe/categories/{category_id}/")
        return response.json()["name"]

    @staticmethod
    def _auth_headers(access_token: str) -> dict:
        return {"Authorization": f"Bearer {access_token}"}

    def get_character_orders(self, character_id: int, access_token: str) -> list[dict]:
        """GET /characters/{character_id}/orders/ — órdenes ACTIVAS del personaje.
        Requiere scope esi-markets.read_character_orders.v1."""
        response = self._get(f"/characters/{character_id}/orders/", headers=self._auth_headers(access_token))
        return response.json()

    def get_character_order_history(self, character_id: int, access_token: str) -> list[dict]:
        """GET /characters/{character_id}/orders/history/ — órdenes cerradas (canceladas,
        expiradas o completadas) de los últimos 90 días. Mismo scope que get_character_orders."""
        orders: list[dict] = []
        page = 1
        while True:
            response = self._get(
                f"/characters/{character_id}/orders/history/",
                params={"page": page}, headers=self._auth_headers(access_token),
            )
            orders.extend(response.json())
            total_pages = int(response.headers.get("X-Pages", 1))
            if page >= total_pages:
                break
            page += 1
        return orders

    def open_market_window(self, type_id: int, access_token: str) -> None:
        """POST /ui/openwindow/marketdetails/ — abre la ventana de mercado del ítem en el
        cliente de EVE del personaje (debe estar logueado en ese momento).
        Requiere scope esi-ui.open_window.v1."""
        self._post(
            "/ui/openwindow/marketdetails/",
            params={"type_id": type_id}, headers=self._auth_headers(access_token),
        )
