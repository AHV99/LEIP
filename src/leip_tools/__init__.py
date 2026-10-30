"""Tools del motor de extracción: consulta, localización de enlaces y lectores.

Los lectores son puros: reciben contenido o rutas locales, nunca descargan URLs.
"""

from .errors import ContentError, TechnicalError, ToolError
from .extract_links import MONTH_YEAR_PATTERN, Link, extract_links
from .http_request import HttpResult, TempFile, http_request, new_session
from .readers import ReadError, read_html, read_pdf, read_spreadsheet

__all__ = [
    "ContentError",
    "TechnicalError",
    "ToolError",
    "HttpResult",
    "TempFile",
    "http_request",
    "new_session",
    "Link",
    "extract_links",
    "MONTH_YEAR_PATTERN",
    "ReadError",
    "read_html",
    "read_pdf",
    "read_spreadsheet",
]
