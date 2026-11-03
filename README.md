# EVE Station Trading Analyzer

Aplicación de escritorio (Python + Tkinter) que evalúa oportunidades de station trading en EVE Online.

Combina un motor de cálculo determinista (spread, comisiones, margen neto, break-even, tamaño de posición),
un Viability Score 0-100 con pesos configurables y *hard stops* que bloquean la operación ante condiciones
críticas. La salida es una recomendación explicable: COMPRAR, COMPRAR CON PRECAUCIÓN, OBSERVAR o NO COMPRAR.

## Estructura

- `domain/`: cálculo puro y reglas de decisión
- `application/`: orquestación del análisis y simulador de escenarios
- `infrastructure/`: configuración y persistencia SQLite
- `presentation/`: interfaz Tkinter
- `config/default_config.json`: umbrales, pesos, costes y capital
- `tests/`: pruebas con pytest

## Uso

```bash
pip install -r requirements.txt
python main.py
python -m pytest
```
