"""Punto de entrada de EVE Station Trading Analyzer (aplicacion de escritorio)."""
from presentation.main_window import MainWindow


def main() -> None:
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
