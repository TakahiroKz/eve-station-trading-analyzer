#!/usr/bin/env python3
"""Pruebas de mutación manuales del módulo de recomendación: introduce un fallo a la vez y comprueba que alguna
prueba lo detecta. Si una mutación sobrevive (las pruebas siguen en verde), falta una prueba.

Uso (en un contenedor con las dependencias de desarrollo, desde la raíz del repo):
    python scripts/mutation_check.py
Trabaja sobre una copia en un directorio temporal; no modifica el repo.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ["tests/test_unit_recommendation.py", "tests/test_unit_recommendation_robustness.py",
         "tests/test_capital_api.py", "tests/test_recomendar_truthfulness.py", "tests/test_eve_calculator.py"]

# (descripción, archivo, texto original, texto con el fallo)
MUTATIONS = [
    ("la comisión de compra no se aplica al costo de una unidad", "backend/api/main.py",
     "unit_cost = buy * eve_config.buy_fee_factor", "unit_cost = buy"),
    ("las unidades ya no se limitan a lo que cabe en la posición", "backend/api/main.py",
     "else min(int(result.unidades_sugeridas or 0), max_units)", "else int(result.unidades_sugeridas or 0)"),
    ("el beneficio vuelve a usar el beneficio unitario redondeado a 2 decimales", "backend/api/main.py",
     "beneficio_neto_isk=round(units * beneficio_unitario(buy, sell, eve_config))",
     "beneficio_neto_isk=round(units * result.beneficio)"),
    ("un ítem rechazado conserva sus unidades", "backend/api/main.py",
     'units = 0 if (action == "REJECT" or not affordable) else', "units = 0 if (not affordable) else"),
    ("se recomienda comprar aunque no quepa ni una unidad", "backend/api/main.py",
     "affordable = max_units >= 1", "affordable = True"),
    ("la posición deja de ser el 10 % (usa el doble)", "backend/api/main.py",
     'pct = float(settings["position_size_pct_wallet"])', 'pct = float(settings["position_size_pct_wallet"]) * 2'),
    ("los días de rotación usan 30 días en vez de 7", "backend/api/main.py",
     'status_row["avg_daily_volume_7d"]', 'status_row["volumen_diario_real"]'),
    ("«candidato a compra» con 0 unidades vuelve a mostrarse", "backend/api/main.py",
     'if units == 0 and action == "BUY_CANDIDATE":', 'if False:'),
    ("el capital deja de redondearse", "backend/api/main.py",
     "step = 10 ** (math.floor(math.log10(capital)) - 1)", "step = 1"),
    ("la caché ignora el capital y los ajustes (la clave solo lleva mercado y ciclo)", "backend/api/main.py",
     "key = (market_id, float(capital), stamp, hash(tuple(sorted(settings.items()))))", "key = (market_id, stamp)"),
    ("sin volumen diario vuelve el error 500", "backend/api/main.py",
     'or not status_row["volumen_diario_real"] or status_row["volumen_diario_real"] <= 0', ""),
    ("la frase del motor vuelve a caer en la rama de liquidez mala con liquidez excelente", "analytics/eve_calculator.py",
     'if liquidez in ("Excelente liquidez", "Buena"):', 'if liquidez == "Buena":'),
    ("el motor vuelve a sugerir más unidades que las deseadas con liquidez mala", "analytics/eve_calculator.py",
     "    objetivo = round(volumen_diario_real * config.recomendacion_objetivo_pct)\n    return (",
     "    objetivo = round(volumen_diario_real * config.recomendacion_objetivo_pct) + round(volumen_deseado)\n    return ("),
    ("el valor por defecto del capital de referencia cambia", "storage/settings_registry.py",
     "1_000_000_000.0,\n    ),\n    SettingDef(\n        \"capture_participation_rate\"", "2_000_000_000.0,\n    ),\n    SettingDef(\n        \"capture_participation_rate\""),
]


def run_tests(tree: Path) -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
                          cwd=tree, capture_output=True, text=True)
    return proc.returncode == 0, (proc.stdout.strip().splitlines() or [""])[-1]


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None   # ejecuta solo las mutaciones cuya descripción lo contiene
    survivors = []
    with tempfile.TemporaryDirectory() as tmp:
        for description, file, original, mutated in MUTATIONS:
            if only and only not in description:
                continue
            tree = Path(tmp) / "tree"
            if tree.exists():
                shutil.rmtree(tree)
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", "node_modules", "dist", "__pycache__",
                                                                      ".ruff_cache", ".pytest_cache"))
            target = tree / file
            text = target.read_text(encoding="utf-8")
            if original not in text:
                print(f"?? no se pudo aplicar: {description} (texto original no encontrado)")
                survivors.append(description + " [no aplicable]")
                continue
            target.write_text(text.replace(original, mutated, 1), encoding="utf-8")
            passed, last = run_tests(tree)
            print(f"{'SOBREVIVE' if passed else 'detectada '}  {description}  ->  {last}")
            if passed:
                survivors.append(description)
    print(f"\nmutaciones: {len(MUTATIONS)}; detectadas: {len(MUTATIONS) - len(survivors)}; sobreviven: {len(survivors)}")
    for s in survivors:
        print("  FALTA UNA PRUEBA PARA:", s)
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
