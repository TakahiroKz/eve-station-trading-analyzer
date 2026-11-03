"""Editor de ordenes BUY/SELL del mercado de EVE Online (seccion 6 de la HU)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List

from domain.models import MarketOrderLevel


class OrderBookSide(ttk.LabelFrame):
    def __init__(self, parent, title: str):
        super().__init__(parent, text=title, padding=6)

        self.tree = ttk.Treeview(self, columns=("price", "qty"), show="headings", height=5)
        self.tree.heading("price", text="Precio")
        self.tree.heading("qty", text="Cantidad")
        self.tree.column("price", width=110, anchor="e")
        self.tree.column("qty", width=90, anchor="e")
        self.tree.pack(side="top", fill="both", expand=True)

        form = ttk.Frame(self)
        form.pack(side="top", fill="x", pady=(6, 0))
        self.price_var = tk.StringVar()
        self.qty_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.price_var, width=12).grid(row=0, column=0, padx=2)
        ttk.Entry(form, textvariable=self.qty_var, width=8).grid(row=0, column=1, padx=2)
        ttk.Button(form, text="Añadir", command=self._add_row).grid(row=0, column=2, padx=2)
        ttk.Button(form, text="Eliminar", command=self._remove_selected).grid(row=0, column=3, padx=2)

    def _add_row(self):
        try:
            price = float(self.price_var.get().replace(",", ""))
            qty = int(float(self.qty_var.get().replace(",", "")))
        except ValueError:
            return
        self.tree.insert("", "end", values=(price, qty))
        self.price_var.set("")
        self.qty_var.set("")

    def _remove_selected(self):
        for item in self.tree.selection():
            self.tree.delete(item)

    def clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def get_levels(self) -> List[MarketOrderLevel]:
        levels = []
        for i, item in enumerate(self.tree.get_children(), start=1):
            price, qty = self.tree.item(item, "values")
            levels.append(MarketOrderLevel(position=i, price=float(price), quantity=int(float(qty))))
        return levels

    def set_levels(self, levels: List[MarketOrderLevel]):
        self.clear()
        for lvl in levels:
            self.tree.insert("", "end", values=(lvl.price, lvl.quantity))


class OrderBookEditor(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.buy_side = OrderBookSide(self, "BUY ORDERS")
        self.sell_side = OrderBookSide(self, "SELL ORDERS")
        self.buy_side.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.sell_side.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
