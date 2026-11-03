"""Registro acumulativo de oportunidades en eve-calculator-registro.xlsx.

Append-only: nunca se sobrescriben filas previas. Las columnas calculadas usan
fórmulas de Excel (no valores fijos), replicando exactamente las fórmulas y
umbrales de analytics/eve_calculator.py, para que el archivo siga siendo
auditable/editable independientemente del script que lo generó.
"""
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

HEADERS = [
    "Fecha", "Item", "Buy", "Sell", "Volumen deseado", "Volumen diario real",
    "Beneficio", "Spread bruto", "Precio min venta", "ROI",
    "Evaluación del spread", "Posición vs volumen diario", "Liquidez", "Recomendación",
]


def _formulas_for_row(r: int) -> dict:
    spread = f"H{r}"
    liquidez = f"M{r}"
    vol_real = f"F{r}"
    return {
        "G": f"=(D{r}*0.901)-(C{r}*1.024)",
        "H": f"=(D{r}/C{r})-1",
        "I": f"=(C{r}*1.024)/0.901",
        "J": f"=((1+{spread})*0.901/1.024)-1",
        "K": (
            f'=IF({spread}<0.14,"❌ Pérdida",'
            f'IF({spread}<0.15,"🟡 Casi cero",'
            f'IF({spread}<0.2,"🟢 Pequeño beneficio",'
            f'IF({spread}<0.3,"🟢 Buen margen",'
            f'IF({spread}<0.5,"🟢🟢 Muy bueno","🟢🟢🟢 Excelente, si existe volumen")))))'
        ),
        "L": f"=E{r}/{vol_real}",
        "M": (
            f'=IF(L{r}<0.1,"Excelente liquidez",'
            f'IF(L{r}<0.25,"Buena",'
            f'IF(L{r}<0.5,"Aceptable",'
            f'IF(L{r}<1,"Cuidado","Muy lenta para tu capital"))))'
        ),
        "N": (
            f'=IF(OR(K{r}="❌ Pérdida",K{r}="🟡 Casi cero"),'
            f'"No ejecutar el trade con estos precios: el spread no cubre costos de forma consistente.",'
            f'IF(AND({liquidez}="Excelente liquidez",OR(K{r}="🟢 Buen margen",K{r}="🟢🟢 Muy bueno",'
            f'K{r}="🟢🟢🟢 Excelente, si existe volumen")),'
            f'"Hay margen para escalar el volumen deseado hasta ~"&ROUND({vol_real}*0.25,0)&'
            f'" unidades (25% del volumen diario) sin salir de una liquidez \'Buena\'.",'
            f'IF({liquidez}="Buena","El volumen deseado está bien calibrado; mantenerlo.",'
            f'IF({liquidez}="Aceptable",'
            f'IF(OR(K{r}="🟢🟢 Muy bueno",K{r}="🟢🟢🟢 Excelente, si existe volumen"),'
            f'"Spread muy favorable: se puede tolerar algo más de posición pese a la liquidez aceptable.",'
            f'"Recorta el volumen hacia ~"&ROUND({vol_real}*0.25,0)&'
            f'" unidades (25% del volumen diario) para mejorar la rotación."),'
            f'"Baja el volumen objetivo a ~"&ROUND({vol_real}*0.4,0)&'
            f'" unidades (40% del volumen diario). Con "&TEXT(L{r},"0%")&'
            f'" del volumen diario el capital puede quedar inmovilizado varios días."'
            f")))))"
        ),
    }


def _ensure_workbook(path: Path) -> tuple:
    if path.exists():
        wb = load_workbook(path)
        return wb, wb["Registro"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Registro"
    ws.append(HEADERS)
    return wb, ws


def _append_row_in_memory(ws: Worksheet, item: str, buy: float, sell: float,
                           volumen_deseado: float, volumen_diario_real: float) -> None:
    next_row = ws.max_row + 1

    ws.cell(row=next_row, column=1, value=date.today().isoformat())
    ws.cell(row=next_row, column=2, value=item)
    ws.cell(row=next_row, column=3, value=buy)
    ws.cell(row=next_row, column=4, value=sell)
    ws.cell(row=next_row, column=5, value=volumen_deseado)
    ws.cell(row=next_row, column=6, value=volumen_diario_real)

    for col_letter, formula in _formulas_for_row(next_row).items():
        ws[f"{col_letter}{next_row}"] = formula


def append_opportunity(path: str, item: str, buy: float, sell: float,
                        volumen_deseado: float, volumen_diario_real: float) -> None:
    """Agrega UNA fila y graba de inmediato. Pensado para uso puntual (chat manual),
    NO para loops de screening batch — ver EveCalculatorRegistro para eso, que evita
    reabrir/regrabar el archivo completo en cada fila (costoso e inestable con miles
    de filas seguidas: puede fallar por contención de E/S en Windows).
    """
    xlsx_path = Path(path)
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)

    wb, ws = _ensure_workbook(xlsx_path)
    _append_row_in_memory(ws, item, buy, sell, volumen_deseado, volumen_diario_real)
    wb.save(xlsx_path)


class EveCalculatorRegistro:
    """Mantiene el workbook en memoria durante un screening batch y graba una sola vez
    (o cada `checkpoint_every` filas, como respaldo ante cortes). Append-only: solo
    agrega filas, nunca reescribe ni elimina las existentes.
    """

    def __init__(self, path: str, checkpoint_every: int = 200):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_every = checkpoint_every
        self._wb, self._ws = _ensure_workbook(self.path)
        self._pending = 0

    def append(self, item: str, buy: float, sell: float,
               volumen_deseado: float, volumen_diario_real: float) -> None:
        _append_row_in_memory(self._ws, item, buy, sell, volumen_deseado, volumen_diario_real)
        self._pending += 1
        if self._pending >= self.checkpoint_every:
            self.save()

    def save(self) -> None:
        if self._pending == 0:
            return
        self._wb.save(self.path)
        self._pending = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.save()
