"""Widgets reutilizables de la GUI."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class LabeledEntry(ttk.Frame):
    """Etiqueta + campo de texto, con acceso a la variable via .var."""

    def __init__(self, parent, label: str, default: str = "", width: int = 14, **kwargs):
        super().__init__(parent)
        ttk.Label(self, text=label).pack(side="top", anchor="w")
        self.var = tk.StringVar(value=default)
        self.entry = ttk.Entry(self, textvariable=self.var, width=width, **kwargs)
        self.entry.pack(side="top", fill="x")

    def get_float(self, default: float = 0.0) -> float:
        try:
            return float(str(self.var.get()).replace(",", "").strip())
        except (ValueError, TypeError):
            return default

    def get_int(self, default: int = 0) -> int:
        try:
            return int(float(str(self.var.get()).replace(",", "").strip()))
        except (ValueError, TypeError):
            return default

    def get_str(self, default: str = "") -> str:
        return str(self.var.get()).strip() or default

    def set(self, value) -> None:
        self.var.set(str(value))


class Section(ttk.LabelFrame):
    """Marco con titulo para agrupar campos, con grid helper."""

    def __init__(self, parent, title: str, **kwargs):
        super().__init__(parent, text=title, padding=8, **kwargs)

    def grid_fields(self, fields, columns: int = 3):
        for i, field in enumerate(fields):
            row, col = divmod(i, columns)
            field.grid(row=row, column=col, padx=6, pady=4, sticky="w")


def rating_color(level_name: str) -> str:
    return {
        "excellent": "#1e8e3e",
        "good": "#1e8e3e",
        "neutral": "#188038",
        "caution": "#e8a300",
        "bad": "#d93025",
    }.get(level_name, "#333333")


def format_isk(value: float) -> str:
    try:
        return f"{value:,.0f} ISK"
    except (TypeError, ValueError):
        return str(value)


def format_pct(value: float) -> str:
    try:
        return f"{value:.2f}%"
    except (TypeError, ValueError):
        return str(value)
