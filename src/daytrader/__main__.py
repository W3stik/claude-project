"""Allows ``python -m daytrader`` when the ``daytrader`` command is not on PATH."""

from daytrader.cli import app

if __name__ == "__main__":
    app(prog_name="daytrader")
