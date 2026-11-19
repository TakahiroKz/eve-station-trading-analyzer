"""La imagen de producción debe llevar todos los paquetes de Python del proyecto (la fase 3 importó `finance` por primera vez
y la API no arrancó porque el Dockerfile no lo copiaba; la CI no lo vio porque las pruebas corren sobre el repositorio)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOT_SHIPPED = {"tests", "scripts"}


def test_every_python_package_is_copied_into_the_image():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    packages = sorted(p.parent.name for p in ROOT.glob("*/__init__.py") if p.parent.name not in NOT_SHIPPED)
    assert "finance" in packages and "backend" in packages
    missing = [name for name in packages if f"COPY {name}/ ./{name}/" not in dockerfile]
    assert not missing, f"faltan en el Dockerfile: {missing}"
