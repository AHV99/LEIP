"""Lectura de formatos sin reglas de bancos ni interpretación económica.

Todas las posiciones son 1-based. Los resultados son serializables a JSON.
Los valores originales se conservan; los decimales solicitados se devuelven
como cadenas exactas en decimal_value, evitando redondeos de float en CSV.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bs4 import BeautifulSoup
import openpyxl
import pdfplumber
import xlrd


class ReadError(ValueError):
    """Contenido ilegible o configuración incompatible con la fuente."""


def _input(data: str | Path | bytes, source: str | None):
    if isinstance(data, bytes):
        return data, source
    path = Path(data)
    return path.read_bytes(), source or str(path.resolve())


def _value(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _cell(value, row, column, **ref):
    return {"value": _value(value), "ref": {**ref, "row": row, "column": column}}


def _decimal(value, separator):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).strip().replace("−", "-")
    if separator == ",":
        if "." in text:
            raise ReadError(f"Separador decimal inesperado en {value!r}")
        text = text.replace(",", ".")
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ReadError(f"Número inválido: {value!r}") from exc
    if not result.is_finite():
        raise ReadError(f"Número no finito: {value!r}")
    return format(result, "f")


def read_spreadsheet(
    data: str | Path | bytes, *, format: str | None = None,
    source: str | None = None, separator: str = ",", decimal: str = ".",
    encoding: str = "utf-8-sig", sheet: str | int = 0,
    header_row: int | None = 1, numeric_columns: tuple[str, ...] | list[str] = (),
) -> dict:
    """Lee CSV, XLSX o XLS. sheet acepta nombre o índice desde cero.

    header_row es la fila de encabezados (desde 1), o None para conservar
    toda la grilla y sus encabezados multinivel. numeric_columns contiene
    nombres exactos. No se infieren fechas, números ni faltantes especiales.
    Excel conserva fórmulas como texto: no calcula ni confía en caches viejas.
    """
    if (header_row is not None and header_row < 1) or decimal not in (".", ","):
        raise ReadError("header_row debe ser positivo y decimal '.' o ','")
    content, origin = _input(data, source)
    kind = (format or (Path(data).suffix if not isinstance(data, bytes) else "")).lower().lstrip(".")
    name = None
    if kind == "csv":
        if len(separator) != 1:
            raise ReadError("separator debe tener un carácter")
        try:
            rows = list(csv.reader(io.StringIO(content.decode(encoding), newline=""), delimiter=separator, strict=True))
        except (UnicodeError, csv.Error) as exc:
            raise ReadError(f"CSV inválido: {exc}") from exc
    elif kind == "xlsx":
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=False)
            try:
                if isinstance(sheet, int) and not 0 <= sheet < len(workbook.worksheets):
                    raise ReadError("Índice de hoja fuera de rango")
                ws = workbook.worksheets[sheet] if isinstance(sheet, int) else workbook[sheet]
                name = ws.title
                # Algunos productores publican dimension=A1 con cientos de filas.
                ws.reset_dimensions()
                rows = list(ws.iter_rows(values_only=True))
            finally:
                workbook.close()
        except (KeyError, IndexError) as exc:
            raise ReadError(f"Hoja inexistente: {sheet!r}") from exc
    elif kind == "xls":
        workbook = xlrd.open_workbook(file_contents=content)
        try:
            if isinstance(sheet, int) and not 0 <= sheet < workbook.nsheets:
                raise ReadError("Índice de hoja fuera de rango")
            try:
                ws = workbook.sheet_by_index(sheet) if isinstance(sheet, int) else workbook.sheet_by_name(sheet)
            except xlrd.XLRDError as exc:
                raise ReadError(f"Hoja inexistente: {sheet!r}") from exc
            name = ws.name
            rows = []
            for r in range(ws.nrows):
                row = []
                for c in range(ws.ncols):
                    cell = ws.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        value = xlrd.xldate_as_datetime(cell.value, workbook.datemode)
                    elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        value = None
                    elif cell.ctype == xlrd.XL_CELL_ERROR:
                        raise ReadError(f"Error Excel en fila {r+1}, columna {c+1}")
                    else:
                        value = cell.value
                    row.append(value)
                rows.append(row)
        finally:
            workbook.release_resources()
    else:
        raise ReadError("Indicar format='csv', 'xlsx' o 'xls' (obligatorio para bytes)")
    if kind != "csv":
        width = max((len(row) for row in rows), default=0)
        rows = [list(row) + [None] * (width-len(row)) for row in rows]
    start = header_row or 0
    if not rows or len(rows) < start:
        raise ReadError("No existe la fila de encabezados")
    headers = ([_value(v) for v in rows[start - 1]] if header_row else
               [openpyxl.utils.get_column_letter(c) for c in range(1, len(rows[0])+1)])
    for column in numeric_columns:
        if headers.count(column) != 1:
            raise ReadError(f"Columna numérica ausente o ambigua: {column!r}")
    output = []
    for r, values in enumerate(rows[start:], start + 1):
        if not values or all(v is None or v == "" for v in values):
            continue
        if len(values) != len(headers):
            raise ReadError(f"Fila {r}: {len(values)} celdas para {len(headers)} columnas")
        cells = []
        for c, value in enumerate(values, 1):
            cell = _cell(None if value == "" else value, r, c, source=origin, sheet=name,
                         coordinate=f"{openpyxl.utils.get_column_letter(c)}{r}")
            if headers[c-1] in numeric_columns:
                # Excel guarda números binarios; decimal configura solo texto.
                cell["decimal_value"] = _decimal(value, decimal if isinstance(value, str) else ".")
            cells.append(cell)
        output.append(cells)
    return {"source": origin, "format": kind, "sheet": name, "header_row": header_row,
            "columns": headers, "rows": output,
            "warnings": ["XLS devuelve resultados almacenados de fórmulas; no recalcula."] if kind == "xls" else []}


def read_pdf(data: str | Path | bytes, *, source: str | None = None,
             pages: list[int] | None = None, table_settings: dict | None = None,
             regions: dict[int, list[dict]] | None = None,
             backend: str = "pdfplumber", ocr: bool = False,
             artifacts_path: str | Path | None = None) -> dict:
    """Extrae texto y tablas con pdfplumber o Docling; páginas desde 1.

    regions={1: [{"bbox": [x0, top, x1, bottom], "table_settings": {...}}]}
    limita tablas a rectángulos en puntos PDF y permite reglas por región.
    El texto completo de cada página se conserva siempre.
    backend='docling' detecta estructura con modelos locales; ocr lo habilita
    explícitamente. No acepta regions/table_settings de pdfplumber.
    """
    if backend not in ("pdfplumber", "docling"):
        raise ReadError("backend debe ser 'pdfplumber' o 'docling'")
    if backend == "docling" and (regions is not None or table_settings is not None):
        raise ReadError("regions/table_settings son opciones de pdfplumber; Docling detecta las tablas")
    if backend == "pdfplumber" and (ocr or artifacts_path is not None):
        raise ReadError("ocr/artifacts_path requieren backend='docling'")
    content, origin = _input(data, source)
    result = {"source": origin, "pages": [], "warnings": []}
    with pdfplumber.open(io.BytesIO(content)) as document:
        selected = list(range(1, len(document.pages)+1)) if pages is None else pages
        if not selected or len(selected) != len(set(selected)) or any(
            not isinstance(p, int) or not 1 <= p <= len(document.pages) for p in selected
        ):
            raise ReadError("pages debe contener páginas válidas, sin duplicados, desde 1")
        if regions is not None and (set(regions) - set(selected)):
            raise ReadError("regions contiene páginas no seleccionadas")
        if backend == "docling":
            from ._docling import extract_pdf
            return extract_pdf(content, origin=origin, pages=selected, ocr=ocr,
                               artifacts_path=str(artifacts_path) if artifacts_path is not None else None)
        for number in selected:
            page = document.pages[number-1]
            text = page.extract_text() or ""
            tables = []
            detected = []
            areas = regions.get(number, []) if regions is not None else []
            if regions is not None and not areas:
                raise ReadError(f"Faltan regiones para la página {number}")
            if areas:
                for area in areas:
                    detected.extend(page.crop(tuple(area["bbox"])).find_tables(
                        area.get("table_settings", table_settings or {})))
            else:
                detected = page.find_tables(table_settings or {})
            for index, table in enumerate(detected, 1):
                rows = []
                for r, values in enumerate(table.extract(), 1):
                    rows.append([_cell(v, r, c, source=origin, page=number, table=index,
                                       bbox=table.rows[r-1].cells[c-1]) for c, v in enumerate(values, 1)])
                tables.append({"index": index, "bbox": table.bbox, "rows": rows})
            if not text.strip():
                result["warnings"].append(f"Página {number}: sin texto extraíble; puede requerir OCR")
            if not tables:
                result["warnings"].append(f"Página {number}: sin tablas detectadas")
            result["pages"].append({"number": number, "text": text, "tables": tables})
    return result


def _normalized(text):
    return " ".join(text.split()).casefold()


def read_html(data: str | Path | bytes, *, source: str | None = None,
              sections: list[str] | None = None, table_selector: str = "table",
              title_selector: str | None = None, encoding: str = "utf-8") -> dict:
    """Lee tablas estáticas; sections selecciona títulos exactos sin distinguir caso.

    Título: selector configurable dentro de la tabla, caption, primera fila
    de título (una celda con colspan), o encabezado h1-h6 precedente.
    rowspan/colspan se expanden conservando la referencia de la celda original.
    """
    content, origin = _input(data, source)
    soup = BeautifulSoup(content.decode(encoding), "html.parser")
    tables, found = [], set()
    wanted = None if sections is None else {_normalized(s) for s in sections}
    for index, table in enumerate(soup.select(table_selector), 1):
        if table.name != "table":
            raise ReadError("table_selector debe seleccionar elementos table")
        if table.find("table"):
            raise ReadError("Tablas anidadas no soportadas: delimitar la tabla de datos")
        title = table.select_one(title_selector) if title_selector else table.find("caption")
        first_row = table.find("tr")
        if title is None and first_row is not None and title_selector is None:
            cells = first_row.find_all(["td", "th"], recursive=False)
            if len(cells) == 1 and int(cells[0].get("colspan", 1)) > 1:
                title = cells[0]
        if title is None and title_selector is None:
            title = table.find_previous(re.compile(r"^h[1-6]$"))
        section = title.get_text(" ", strip=True) if title else ""
        if wanted is not None and _normalized(section) not in wanted:
            continue
        found.add(_normalized(section))
        grid = {}
        html_rows = table.find_all("tr")
        for r, row in enumerate(html_rows, 1):
            c = 1
            for element in row.find_all(["th", "td"], recursive=False):
                while (r, c) in grid:
                    c += 1
                rowspan, colspan = int(element.get("rowspan", 1)), int(element.get("colspan", 1))
                if rowspan < 1 or colspan < 1 or r + rowspan - 1 > len(html_rows):
                    raise ReadError("rowspan/colspan inválido o fuera de tabla")
                cell = _cell(element.get_text(" ", strip=True) or None, r, c,
                             source=origin, section=section, table=index)
                cell.update(rowspan=rowspan, colspan=colspan, header=element.name == "th")
                for rr in range(r, r+rowspan):
                    for cc in range(c, c+colspan):
                        if (rr, cc) in grid:
                            raise ReadError("Celdas combinadas superpuestas")
                        grid[rr, cc] = cell
                c += colspan
        width = max((c for r, c in grid), default=0)
        rows = [[grid.get((r, c)) for c in range(1, width+1)] for r in range(1, len(html_rows)+1)]
        tables.append({"index": index, "section": section, "rows": rows})
    if wanted is not None and wanted - found:
        raise ReadError(f"Secciones no encontradas: {sorted(wanted - found)}")
    if not tables:
        raise ReadError("No se encontraron tablas HTML")
    return {"source": origin, "tables": tables}
