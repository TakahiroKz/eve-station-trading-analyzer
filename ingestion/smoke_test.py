"""Verifica conectividad básica con la ESI antes de continuar con el backfill."""
import os
import sys

from dotenv import load_dotenv

from ingestion.esi_client import EsiClient, DEFAULT_BASE_URL


def main() -> int:
    load_dotenv()
    region_id = int(os.environ.get("ESI_REGION_ID", 10000002))
    base_url = os.environ.get("ESI_BASE_URL", DEFAULT_BASE_URL)
    user_agent = os.environ.get("ESI_USER_AGENT", "eve-market-screener")

    with EsiClient(base_url=base_url, user_agent=user_agent) as client:
        type_ids = client.get_active_type_ids(region_id)
        print(f"OK: {len(type_ids)} tipos activos en la region {region_id}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
