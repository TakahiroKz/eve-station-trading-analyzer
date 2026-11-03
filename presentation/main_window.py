"""Ventana principal de EVE Station Trading Analyzer.

Presentation Layer: no contiene logica de negocio. Delega en application/* para el analisis
y en infrastructure/* para persistencia y configuracion.
"""
from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Optional

from application.analysis_result import AnalysisResult
from application.product_analysis_service import analyze_product
from application.scenario_simulator import SimulationInput, simulate, simulate_scenarios
from domain.models import CostConfig, EveHubSnapshot, MarketSnapshot, ProductInput
from infrastructure import analysis_repository, trade_repository
from infrastructure.config_repository import AppConfig, load_config, save_config
from infrastructure.database import init_db

from presentation.order_book_editor import OrderBookEditor
from presentation.scrollable_frame import ScrollableFrame
from presentation.widgets import LabeledEntry, format_isk, format_pct, rating_color


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EVE Station Trading Analyzer")
        self.geometry("1180x780")

        init_db()
        self.app_config: AppConfig = load_config()
        self.last_result: Optional[AnalysisResult] = None
        self.last_result_id: Optional[int] = None

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.tab_analysis = ttk.Frame(notebook)
        self.tab_simulator = ttk.Frame(notebook)
        self.tab_history = ttk.Frame(notebook)
        self.tab_trades = ttk.Frame(notebook)
        self.tab_config = ttk.Frame(notebook)

        notebook.add(self.tab_analysis, text="Análisis")
        notebook.add(self.tab_simulator, text="Simulador")
        notebook.add(self.tab_history, text="Historial")
        notebook.add(self.tab_trades, text="Operaciones")
        notebook.add(self.tab_config, text="Configuración")

        self._build_analysis_tab()
        self._build_simulator_tab()
        self._build_history_tab()
        self._build_trades_tab()
        self._build_config_tab()

        self._refresh_capital_banner()
        self._refresh_history()
        self._refresh_trades()

    # ------------------------------------------------------------------
    # TAB: ANALISIS
    # ------------------------------------------------------------------
    def _build_analysis_tab(self):
        scroll = ScrollableFrame(self.tab_analysis)
        scroll.pack(fill="both", expand=True)
        root = scroll.inner

        self.capital_banner = ttk.Label(root, font=("Segoe UI", 11, "bold"))
        self.capital_banner.pack(anchor="w", padx=10, pady=(10, 4))

        columns = ttk.Frame(root)
        columns.pack(fill="both", expand=True, padx=10)
        left = ttk.Frame(columns)
        right = ttk.Frame(columns)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        # --- Producto ---
        prod_box = ttk.LabelFrame(left, text="PRODUCTO", padding=8)
        prod_box.pack(fill="x", pady=4)
        self.f_item = LabeledEntry(prod_box, "Item", "Imperial Navy Gamma L", width=30)
        self.f_item.pack(fill="x")

        # --- EVE-Hub ---
        hub_box = ttk.LabelFrame(left, text="EVE-HUB (datos observados, no recalculados)", padding=8)
        hub_box.pack(fill="x", pady=4)
        grid = ttk.Frame(hub_box)
        grid.pack(fill="x")
        self.f_buy = LabeledEntry(grid, "Buy", "698000")
        self.f_sell = LabeledEntry(grid, "Sell", "997900")
        self.f_vwap = LabeledEntry(grid, "VWAP", "836000")
        self.f_hub_profit_unit = LabeledEntry(grid, "Profit/Unit", "179400")
        self.f_hub_margin = LabeledEntry(grid, "Margin %", "25.1")
        self.f_volume_day = LabeledEntry(grid, "Volume/day", "390")
        self.f_trend = LabeledEntry(grid, "Trend %", "26.2")
        self.f_volatility = LabeledEntry(grid, "Volatility %", "19.0")
        self.f_hub_profit_day = LabeledEntry(grid, "Profit/day", "13980000")
        fields = [
            self.f_buy, self.f_sell, self.f_vwap,
            self.f_hub_profit_unit, self.f_hub_margin, self.f_volume_day,
            self.f_trend, self.f_volatility, self.f_hub_profit_day,
        ]
        for i, f in enumerate(fields):
            f.grid(row=i // 3, column=i % 3, padx=6, pady=4, sticky="w")

        # --- Mi orden ---
        my_box = ttk.LabelFrame(left, text="MI ORDEN", padding=8)
        my_box.pack(fill="x", pady=4)
        self.f_my_buy = LabeledEntry(my_box, "Mi Buy Price", "698000")
        self.f_my_sell = LabeledEntry(my_box, "Mi Sell Price", "997900")
        self.f_my_qty = LabeledEntry(my_box, "Cantidad (vacio = auto)", "")
        self.f_my_buy.grid(row=0, column=0, padx=6, pady=4)
        self.f_my_sell.grid(row=0, column=1, padx=6, pady=4)
        self.f_my_qty.grid(row=0, column=2, padx=6, pady=4)

        # --- Mercado ---
        market_box = ttk.LabelFrame(left, text="EVE MARKET (profundidad)", padding=8)
        market_box.pack(fill="both", pady=4)
        self.order_book = OrderBookEditor(market_box)
        self.order_book.pack(fill="both", expand=True)

        ttk.Button(left, text="Analizar", command=self._run_analysis).pack(pady=8)
        self.save_btn = ttk.Button(left, text="Guardar en historial", command=self._save_current_analysis, state="disabled")
        self.save_btn.pack(pady=(0, 12))

        # --- Resultados ---
        self.results_frame = ttk.Frame(right)
        self.results_frame.pack(fill="both", expand=True)
        ttk.Label(self.results_frame, text="Pulsa 'Analizar' para ver los resultados.").pack(anchor="w")

    def _refresh_capital_banner(self):
        c = self.app_config.capital
        self.capital_banner.config(
            text=(
                f"CAPITAL: {format_isk(c.total_isk)}   |   "
                f"Trading: {format_isk(c.trading_isk)}   |   Reserva: {format_isk(c.reserve_isk)}   |   "
                f"Máx. posición: {c.max_pct_per_position:.0f}%   |   Máx. producto: {c.max_pct_per_product:.0f}%"
            )
        )

    def _build_product_input(self) -> Optional[ProductInput]:
        try:
            eve_hub = EveHubSnapshot(
                item=self.f_item.get_str("Producto"),
                buy=self.f_buy.get_float(),
                sell=self.f_sell.get_float(),
                vwap=self.f_vwap.get_float(),
                profit_per_unit=self.f_hub_profit_unit.get_float(),
                margin_pct=self.f_hub_margin.get_float(),
                volume_day=self.f_volume_day.get_float(),
                trend_pct=self.f_trend.get_float(),
                volatility_pct=self.f_volatility.get_float(),
                profit_day=self.f_hub_profit_day.get_float(),
                captured_at=datetime.now(),
            )
            market = MarketSnapshot(
                buy_orders=self.order_book.buy_side.get_levels(),
                sell_orders=self.order_book.sell_side.get_levels(),
            )
            qty_raw = self.f_my_qty.get_str("")
            qty = self.f_my_qty.get_int() if qty_raw else None
            return ProductInput(
                item=eve_hub.item,
                eve_hub=eve_hub,
                market=market,
                my_buy_price=self.f_my_buy.get_float(),
                my_sell_price=self.f_my_sell.get_float(),
                my_quantity=qty,
            )
        except Exception as exc:  # noqa: BLE001 - mostrado al usuario, no logica critica
            messagebox.showerror("Datos invalidos", str(exc))
            return None

    def _run_analysis(self):
        product = self._build_product_input()
        if product is None:
            return
        if product.my_buy_price <= 0:
            messagebox.showerror("Datos invalidos", "El precio de compra debe ser mayor que 0.")
            return
        try:
            result = analyze_product(product, self.app_config)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Error de calculo", str(exc))
            return
        self.last_result = result
        self.save_btn.config(state="normal")
        self._render_results(result)
        # Pre-carga el simulador con los datos recien analizados
        self._preload_simulator(product)

    def _render_results(self, r: AnalysisResult):
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        def section(title):
            box = ttk.LabelFrame(self.results_frame, text=title, padding=8)
            box.pack(fill="x", pady=4)
            return box

        def row(parent, label, value, color=None):
            line = ttk.Frame(parent)
            line.pack(fill="x", anchor="w")
            ttk.Label(line, text=label, width=28).pack(side="left")
            lbl = tk.Label(line, text=str(value), fg=color or "black")
            lbl.pack(side="left")

        calc = section("CÁLCULO")
        row(calc, "Spread bruto:", f"{format_isk(r.spread.spread_isk)}  ({format_pct(r.spread.spread_pct)})")
        row(calc, "Beneficio bruto/unidad:", format_isk(r.profit.gross_profit_unit))
        row(calc, "  Broker BUY:", format_isk(-r.fees.broker_fee_buy))
        row(calc, "  Broker SELL:", format_isk(-r.fees.broker_fee_sell))
        row(calc, "  Sales Tax:", format_isk(-r.fees.sales_tax))
        row(calc, "  Relist:", format_isk(-r.fees.relist_cost))
        row(calc, "Beneficio neto/unidad:", format_isk(r.profit.net_profit_unit))
        row(calc, "Margen neto:", format_pct(r.net_margin_pct))
        row(calc, "ROI:", format_pct(r.capital_efficiency.roi_pct))
        row(calc, "Break-even sell price:", format_isk(r.breakeven_price))
        row(calc, "Margen de seguridad:", format_pct(r.safety_margin_pct))

        comp = section("COMPARACIÓN EVE-HUB vs SISTEMA")
        row(comp, "Profit/unit EVE-Hub:", format_isk(r.eve_hub_profit_unit))
        row(comp, "Profit/unit Sistema:", format_isk(r.profit.net_profit_unit))
        d = r.profit_unit_discrepancy
        row(comp, "Diferencia:", f"{format_isk(d.difference)}  ({format_pct(d.difference_pct)})",
            color="#d93025" if d.is_significant else "black")
        row(comp, "Margin EVE-Hub:", format_pct(r.eve_hub_margin_pct))
        row(comp, "Margin Sistema:", format_pct(r.net_margin_pct))
        dm = r.margin_discrepancy
        row(comp, "Diferencia:", f"{format_pct(dm.difference)}",
            color="#d93025" if dm.is_significant else "black")
        if d.is_significant or dm.is_significant:
            row(comp, "", "⚠️ Advertencia: los cálculos propios no coinciden con EVE-Hub.", color="#d93025")

        pos = section("POSICIÓN")
        row(pos, "Capital máximo por producto:", format_isk(r.position_size.max_capital_per_product))
        row(pos, "Precio unidad:", format_isk(r.buy_price))
        row(pos, "Máximo por capital:", f"{r.position_size.max_units_by_capital} unidades")
        row(pos, "Capital usado:", format_isk(r.position_size.capital_used))
        row(pos, "Posición vs volumen diario:", format_pct(r.position_size.position_vs_volume_pct))
        row(pos, "Unidades por delante (sell):", f"{r.units_ahead_sell}")
        row(pos, "Compatible con capital:", "Sí" if r.position_compatibility.compatible else "No",
            color=None if r.position_compatibility.compatible else "#d93025")

        risk = section("RIESGO Y LIQUIDEZ")
        for label, rating in (
            ("Tendencia", r.trend_rating), ("Volatilidad", r.volatility_rating),
            ("Spread", r.spread_rating), ("Liquidez", r.liquidity_rating),
            ("Profundidad", r.market_depth_rating),
        ):
            row(risk, f"{label}:", f"{rating.emoji} {rating.label}", color=rating_color(rating.level.value))

        capeff = section("CAPITAL EFFICIENCY / TURNOVER")
        row(capeff, "Beneficio estimado (posición):", format_isk(r.capital_efficiency.estimated_profit))
        row(capeff, "Beneficio diario estimado:", format_isk(r.estimated_profit_per_day))
        row(capeff, "", "Estimación basada en volumen histórico; no representa una garantía de ejecución.", color="#666")
        turnover_txt = (
            f"{r.capital_turnover.days_to_recover:.1f} días" if r.capital_turnover.days_to_recover else "N/A"
        )
        row(capeff, "Recuperación de capital (teórica):", turnover_txt)

        score_box = section("VIABILITY SCORE")
        row(score_box, "Score:", f"{r.score.total_score:.0f} / 100")

        rec_box = section("RECOMENDACIÓN")
        rec = r.recommendation
        color = {"BUY": "#1e8e3e", "BUY_WITH_CAUTION": "#e8a300", "WATCH": "#1a73e8", "DO_NOT_BUY": "#d93025"}[rec.status.value]
        big = tk.Label(rec_box, text=rec.label, font=("Segoe UI", 14, "bold"), fg=color)
        big.pack(anchor="w", pady=(0, 4))
        ttk.Label(rec_box, text=rec.narrative, wraplength=480, justify="left").pack(anchor="w", pady=(0, 6))
        row(rec_box, "Confianza:", f"{rec.confidence:.0f}/100")
        row(rec_box, "Cantidad recomendada:", f"{r.position_size.max_units_by_capital} unidades")
        row(rec_box, "Capital:", format_isk(r.position_size.capital_used))

        if rec.hard_stop_messages:
            ttk.Label(rec_box, text="Condiciones críticas (hard stop):", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
            for m in rec.hard_stop_messages:
                tk.Label(rec_box, text=f"⛔ {m}", fg="#d93025", wraplength=480, justify="left").pack(anchor="w")

        if rec.reasons:
            ttk.Label(rec_box, text="Principales razones:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
            for reason in rec.reasons:
                tk.Label(rec_box, text=f"+ {reason}", fg="#1e8e3e", wraplength=480, justify="left").pack(anchor="w")

        if rec.risks:
            ttk.Label(rec_box, text="Riesgos:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
            for riskline in rec.risks:
                tk.Label(rec_box, text=f"- {riskline}", fg="#e8a300", wraplength=480, justify="left").pack(anchor="w")

        ttk.Label(rec_box, text="Condición para cancelar:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
        ttk.Label(rec_box, text=rec.cancel_condition, wraplength=480, justify="left").pack(anchor="w")

    def _save_current_analysis(self):
        if self.last_result is None:
            return
        product = self._build_product_input()
        if product is None:
            return
        input_dict = {
            "item": product.item,
            "eve_hub": product.eve_hub.__dict__,
            "my_buy_price": product.my_buy_price,
            "my_sell_price": product.my_sell_price,
            "my_quantity": product.my_quantity,
        }
        analysis_id = analysis_repository.save_analysis(
            product.item, input_dict, self.last_result.to_summary_dict()
        )
        self.last_result_id = analysis_id
        messagebox.showinfo("Guardado", f"Análisis #{analysis_id} guardado en el historial.")
        self._refresh_history()

    # ------------------------------------------------------------------
    # TAB: SIMULADOR
    # ------------------------------------------------------------------
    def _build_simulator_tab(self):
        root = ttk.Frame(self.tab_simulator, padding=12)
        root.pack(fill="both", expand=True)

        form = ttk.LabelFrame(root, text="Parámetros de simulación", padding=8)
        form.pack(fill="x")
        self.s_capital = LabeledEntry(form, "Capital", "50000000")
        self.s_buy = LabeledEntry(form, "Buy", "698000")
        self.s_sell = LabeledEntry(form, "Sell", "997900")
        self.s_qty = LabeledEntry(form, "Cantidad", "7")
        self.s_broker_buy = LabeledEntry(form, "Broker BUY %", str(self.app_config.costs.broker_fee_buy_pct))
        self.s_broker_sell = LabeledEntry(form, "Broker SELL %", str(self.app_config.costs.broker_fee_sell_pct))
        self.s_tax = LabeledEntry(form, "Sales Tax %", str(self.app_config.costs.sales_tax_pct))
        self.s_relist = LabeledEntry(form, "Relist %", str(self.app_config.costs.relist_fee_pct))
        fields = [self.s_capital, self.s_buy, self.s_sell, self.s_qty, self.s_broker_buy, self.s_broker_sell, self.s_tax, self.s_relist]
        for i, f in enumerate(fields):
            f.grid(row=i // 4, column=i % 4, padx=6, pady=4, sticky="w")

        ttk.Button(root, text="Recalcular", command=self._run_simulation).pack(pady=8)

        self.sim_results = ttk.Frame(root)
        self.sim_results.pack(fill="x", pady=6)

        self.scenario_tree = ttk.Treeview(root, columns=("escenario", "precio", "beneficio"), show="headings", height=4)
        self.scenario_tree.heading("escenario", text="Escenario")
        self.scenario_tree.heading("precio", text="Precio venta")
        self.scenario_tree.heading("beneficio", text="Beneficio")
        self.scenario_tree.pack(fill="x", pady=6)

    def _preload_simulator(self, product: ProductInput):
        self.s_buy.set(product.my_buy_price)
        self.s_sell.set(product.my_sell_price)
        if self.last_result is not None:
            self.s_qty.set(self.last_result.position_size.max_units_by_capital)

    def _current_sim_costs(self) -> CostConfig:
        return CostConfig(
            broker_fee_buy_pct=self.s_broker_buy.get_float(),
            broker_fee_sell_pct=self.s_broker_sell.get_float(),
            sales_tax_pct=self.s_tax.get_float(),
            relist_fee_pct=self.s_relist.get_float(),
        )

    def _run_simulation(self):
        try:
            inp = SimulationInput(
                capital=self.s_capital.get_float(),
                buy_price=self.s_buy.get_float(),
                sell_price=self.s_sell.get_float(),
                quantity=self.s_qty.get_int(),
                costs=self._current_sim_costs(),
            )
            result = simulate(inp)
            scenarios = simulate_scenarios(inp)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Error de simulación", str(exc))
            return

        for w in self.sim_results.winfo_children():
            w.destroy()

        def row(label, value):
            line = ttk.Frame(self.sim_results)
            line.pack(fill="x", anchor="w")
            ttk.Label(line, text=label, width=22).pack(side="left")
            ttk.Label(line, text=value).pack(side="left")

        row("Capital utilizado:", format_isk(result.capital_used))
        row("Revenue:", format_isk(result.revenue))
        row("Fees totales:", format_isk(result.fees_total))
        row("Profit:", format_isk(result.profit))
        row("ROI:", format_pct(result.roi_pct))
        row("Margin:", format_pct(result.margin_pct))
        row("Break-even sell price:", format_isk(result.breakeven_sell_price))

        for item in self.scenario_tree.get_children():
            self.scenario_tree.delete(item)
        for s in scenarios:
            self.scenario_tree.insert("", "end", values=(s.name, format_isk(s.sell_price), format_isk(s.profit)))

    # ------------------------------------------------------------------
    # TAB: HISTORIAL
    # ------------------------------------------------------------------
    def _build_history_tab(self):
        root = ttk.Frame(self.tab_history, padding=12)
        root.pack(fill="both", expand=True)

        cols = ("id", "fecha", "item", "buy", "sell", "margin", "score", "recomendación")
        self.history_tree = ttk.Treeview(root, columns=cols, show="headings")
        for c, w in zip(cols, (40, 140, 200, 90, 90, 80, 60, 160)):
            self.history_tree.heading(c, text=c.capitalize())
            self.history_tree.column(c, width=w)
        self.history_tree.pack(fill="both", expand=True)
        self.history_tree.bind("<Double-1>", self._show_history_detail)

        ttk.Button(root, text="Refrescar", command=self._refresh_history).pack(pady=6)

    def _refresh_history(self):
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for a in analysis_repository.list_analyses():
            self.history_tree.insert("", "end", iid=str(a["id"]), values=(
                a["id"], a["created_at"], a["item"],
                format_isk(a["buy_price"]), format_isk(a["sell_price"]),
                format_pct(a["calc_net_margin_pct"]), f"{a['score']:.0f}",
                a["recommendation_label"],
            ))

    def _show_history_detail(self, _event):
        selection = self.history_tree.selection()
        if not selection:
            return
        analysis = analysis_repository.get_analysis(int(selection[0]))
        if not analysis:
            return
        result = json.loads(analysis["result_json"])
        detail = "\n".join(f"{k}: {v}" for k, v in result.items())
        top = tk.Toplevel(self)
        top.title(f"Análisis #{analysis['id']} - {analysis['item']}")
        text = tk.Text(top, width=80, height=30)
        text.insert("1.0", detail)
        text.config(state="disabled")
        text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # TAB: OPERACIONES (trade journal)
    # ------------------------------------------------------------------
    def _build_trades_tab(self):
        root = ttk.Frame(self.tab_trades, padding=12)
        root.pack(fill="both", expand=True)

        form = ttk.LabelFrame(root, text="Registrar operación real", padding=8)
        form.pack(fill="x")
        self.t_analysis_id = LabeledEntry(form, "ID Análisis (opcional)", "")
        self.t_item = LabeledEntry(form, "Item", "")
        self.t_units = LabeledEntry(form, "Unidades compradas", "")
        self.t_real_buy = LabeledEntry(form, "Precio real compra", "")
        self.t_real_sell = LabeledEntry(form, "Precio real venta", "")
        self.t_hours = LabeledEntry(form, "Tiempo (horas)", "")
        self.t_notes = LabeledEntry(form, "Notas", "", width=30)
        fields = [self.t_analysis_id, self.t_item, self.t_units, self.t_real_buy, self.t_real_sell, self.t_hours, self.t_notes]
        for i, f in enumerate(fields):
            f.grid(row=i // 4, column=i % 4, padx=6, pady=4, sticky="w")

        ttk.Button(root, text="Registrar operación", command=self._save_trade).pack(pady=8)

        cols = ("id", "fecha", "item", "unidades", "buy_real", "sell_real", "profit_real")
        self.trades_tree = ttk.Treeview(root, columns=cols, show="headings")
        for c, w in zip(cols, (40, 140, 200, 80, 90, 90, 90)):
            self.trades_tree.heading(c, text=c.capitalize())
            self.trades_tree.column(c, width=w)
        self.trades_tree.pack(fill="both", expand=True, pady=6)

    def _save_trade(self):
        try:
            units = self.t_units.get_int()
            real_buy = self.t_real_buy.get_float()
            real_sell_raw = self.t_real_sell.get_str("")
            real_sell = self.t_real_sell.get_float() if real_sell_raw else None
            real_profit = (real_sell - real_buy) * units if real_sell is not None else None
            analysis_id_raw = self.t_analysis_id.get_str("")
            analysis_id = int(analysis_id_raw) if analysis_id_raw else None
            trade_repository.save_trade(
                item=self.t_item.get_str("Producto"),
                units_bought=units,
                real_buy_price=real_buy,
                analysis_id=analysis_id,
                real_sell_price=real_sell,
                hours_to_sell=self.t_hours.get_float() if self.t_hours.get_str("") else None,
                real_profit=real_profit,
                notes=self.t_notes.get_str(""),
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Datos inválidos", str(exc))
            return
        self._refresh_trades()

    def _refresh_trades(self):
        for item in self.trades_tree.get_children():
            self.trades_tree.delete(item)
        for t in trade_repository.list_trades():
            self.trades_tree.insert("", "end", values=(
                t["id"], t["created_at"], t["item"], t["units_bought"],
                format_isk(t["real_buy_price"]),
                format_isk(t["real_sell_price"]) if t["real_sell_price"] is not None else "-",
                format_isk(t["real_profit"]) if t["real_profit"] is not None else "-",
            ))

    # ------------------------------------------------------------------
    # TAB: CONFIGURACIÓN
    # ------------------------------------------------------------------
    def _build_config_tab(self):
        scroll = ScrollableFrame(self.tab_config)
        scroll.pack(fill="both", expand=True)
        root = scroll.inner
        pad = ttk.Frame(root, padding=12)
        pad.pack(fill="both", expand=True)

        cap = self.app_config.capital
        cap_box = ttk.LabelFrame(pad, text="Capital y posición", padding=8)
        cap_box.pack(fill="x", pady=4)
        self.c_total = LabeledEntry(cap_box, "Capital total", str(cap.total_isk))
        self.c_trading = LabeledEntry(cap_box, "Capital trading", str(cap.trading_isk))
        self.c_reserve = LabeledEntry(cap_box, "Reserva", str(cap.reserve_isk))
        self.c_max_pos = LabeledEntry(cap_box, "Máx % por posición", str(cap.max_pct_per_position))
        self.c_max_prod = LabeledEntry(cap_box, "Máx % por producto", str(cap.max_pct_per_product))
        for i, f in enumerate([self.c_total, self.c_trading, self.c_reserve, self.c_max_pos, self.c_max_prod]):
            f.grid(row=0, column=i, padx=6, pady=4)

        costs = self.app_config.costs
        cost_box = ttk.LabelFrame(pad, text="Costes", padding=8)
        cost_box.pack(fill="x", pady=4)
        self.cf_broker_buy = LabeledEntry(cost_box, "Broker BUY %", str(costs.broker_fee_buy_pct))
        self.cf_broker_sell = LabeledEntry(cost_box, "Broker SELL %", str(costs.broker_fee_sell_pct))
        self.cf_tax = LabeledEntry(cost_box, "Sales Tax %", str(costs.sales_tax_pct))
        self.cf_relist = LabeledEntry(cost_box, "Relist %", str(costs.relist_fee_pct))
        for i, f in enumerate([self.cf_broker_buy, self.cf_broker_sell, self.cf_tax, self.cf_relist]):
            f.grid(row=0, column=i, padx=6, pady=4)

        hs = self.app_config.hard_stops
        hs_box = ttk.LabelFrame(pad, text="Hard Stops", padding=8)
        hs_box.pack(fill="x", pady=4)
        self.hs_trend = LabeledEntry(hs_box, "Trend mínimo %", str(hs.trend_min_pct))
        self.hs_vol = LabeledEntry(hs_box, "Volatility máxima %", str(hs.volatility_max_pct))
        self.hs_margin = LabeledEntry(hs_box, "Net margin mínimo %", str(hs.net_margin_min_pct))
        for i, f in enumerate([self.hs_trend, self.hs_vol, self.hs_margin]):
            f.grid(row=0, column=i, padx=6, pady=4)

        w = self.app_config.score_weights
        w_box = ttk.LabelFrame(pad, text="Pesos del Viability Score (%)", padding=8)
        w_box.pack(fill="x", pady=4)
        self.w_margin = LabeledEntry(w_box, "Margen neto", str(w.net_margin))
        self.w_profit_unit = LabeledEntry(w_box, "Profit/Unit", str(w.profit_unit))
        self.w_liquidity = LabeledEntry(w_box, "Liquidez", str(w.liquidity))
        self.w_profit_day = LabeledEntry(w_box, "Profit/day", str(w.profit_day))
        self.w_trend = LabeledEntry(w_box, "Tendencia", str(w.trend))
        self.w_volatility = LabeledEntry(w_box, "Volatilidad", str(w.volatility))
        self.w_cap_eff = LabeledEntry(w_box, "Capital Efficiency", str(w.capital_efficiency))
        self.w_depth = LabeledEntry(w_box, "Market Depth", str(w.market_depth))
        w_fields = [self.w_margin, self.w_profit_unit, self.w_liquidity, self.w_profit_day,
                    self.w_trend, self.w_volatility, self.w_cap_eff, self.w_depth]
        for i, f in enumerate(w_fields):
            f.grid(row=i // 4, column=i % 4, padx=6, pady=4)

        ttk.Button(pad, text="Guardar configuración", command=self._save_config_from_form).pack(pady=10)

    def _save_config_from_form(self):
        raw = self.app_config.raw
        try:
            raw["capital"]["total_isk"] = self.c_total.get_float()
            raw["capital"]["trading_isk"] = self.c_trading.get_float()
            raw["capital"]["reserve_isk"] = self.c_reserve.get_float()
            raw["capital"]["max_pct_per_position"] = self.c_max_pos.get_float()
            raw["capital"]["max_pct_per_product"] = self.c_max_prod.get_float()

            raw["costs"]["broker_fee_buy_pct"] = self.cf_broker_buy.get_float()
            raw["costs"]["broker_fee_sell_pct"] = self.cf_broker_sell.get_float()
            raw["costs"]["sales_tax_pct"] = self.cf_tax.get_float()
            raw["costs"]["relist_fee_pct"] = self.cf_relist.get_float()

            raw["hard_stops"]["trend_min_pct"] = self.hs_trend.get_float()
            raw["hard_stops"]["volatility_max_pct"] = self.hs_vol.get_float()
            raw["hard_stops"]["net_margin_min_pct"] = self.hs_margin.get_float()

            raw["score_weights"]["net_margin"] = self.w_margin.get_float()
            raw["score_weights"]["profit_unit"] = self.w_profit_unit.get_float()
            raw["score_weights"]["liquidity"] = self.w_liquidity.get_float()
            raw["score_weights"]["profit_day"] = self.w_profit_day.get_float()
            raw["score_weights"]["trend"] = self.w_trend.get_float()
            raw["score_weights"]["volatility"] = self.w_volatility.get_float()
            raw["score_weights"]["capital_efficiency"] = self.w_cap_eff.get_float()
            raw["score_weights"]["market_depth"] = self.w_depth.get_float()

            save_config(self.app_config)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Error al guardar", str(exc))
            return

        self._refresh_capital_banner()
        messagebox.showinfo("Configuración", "Configuración guardada correctamente.")
