"""Lectores puros: reciben contenido o rutas locales, nunca descargan URLs."""

from .readers import ReadError, read_html, read_pdf, read_spreadsheet

__all__ = ["ReadError", "read_html", "read_pdf", "read_spreadsheet"]
