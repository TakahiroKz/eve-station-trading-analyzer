"""Frame con scroll vertical, usado para pantallas con mas contenido del que cabe en la ventana."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vscroll.set)

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        if str(self.canvas.winfo_containing(event.x_root, event.y_root)).startswith(str(self.canvas)):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
