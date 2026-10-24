"""Adaptador privado de Docling para read_pdf; no agrega una cuarta tool."""
from functools import lru_cache
from importlib.metadata import version
from io import BytesIO


@lru_cache(maxsize=4)
def _converter(ocr, artifacts_path):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    if artifacts_path is not None:
        options.artifacts_path = artifacts_path
    return DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=options),
    })


def _box(bbox, height):
    if bbox is None:
        return None
    box = bbox.to_top_left_origin(page_height=height)
    return [box.l, box.t, box.r, box.b]


def extract_pdf(content, *, origin, pages, ocr, artifacts_path):
    from .readers import ReadError

    try:
        from docling.datamodel.base_models import ConversionStatus, DocumentStream
    except ImportError as exc:
        raise ReadError('Instalar Docling con: python -m pip install -e ".[docling]"') from exc

    converter = _converter(ocr, artifacts_path)
    conversion = converter.convert(
        DocumentStream(name="input.pdf", stream=BytesIO(content)),
        page_range=(min(pages), max(pages)), raises_on_error=True,
    )
    if conversion.status != ConversionStatus.SUCCESS:
        raise ReadError(f"Docling no completó la conversión: {conversion.status}")
    doc = conversion.document
    result = {"source": origin, "backend": "docling", "backend_version": version("docling"),
              "ocr": ocr, "pages": [], "warnings": []}
    for number in pages:
        if number not in doc.pages:
            raise ReadError(f"Docling no devolvió la página solicitada {number}")
        height = doc.pages[number].size.height
        tables = []
        for table in doc.tables:
            table_pages = sorted({prov.page_no for prov in table.prov})
            if number not in table_pages:
                continue
            # Las tablas multipágina requieren un contrato que identifique
            # la página de cada celda. No asignarles una ubicación inventada.
            if table_pages != [number]:
                raise ReadError("Docling devolvió una tabla multipágina: falta definir referencias por celda")
            data = table.data
            rows = [[None for _ in range(data.num_cols)] for _ in range(data.num_rows)]
            index = len(tables)+1
            for cell_number, cell in enumerate(data.table_cells):
                r0, r1 = cell.start_row_offset_idx, cell.end_row_offset_idx
                c0, c1 = cell.start_col_offset_idx, cell.end_col_offset_idx
                if not (0 <= r0 < r1 <= data.num_rows and 0 <= c0 < c1 <= data.num_cols):
                    raise ReadError("Docling devolvió una celda fuera de la grilla")
                text = cell.text
                if hasattr(cell, "ref"):
                    raise ReadError("Celda Docling con contenido enriquecido no soportada todavía")
                value = {"value": text if text else None,
                         "ref": {"source": origin, "page": number, "table": index,
                                 "row": r0+1, "column": c0+1,
                                 "bbox": _box(cell.bbox, height),
                                 "docling_ref": f"{table.self_ref}/data/table_cells/{cell_number}"},
                         "rowspan": r1-r0, "colspan": c1-c0,
                         "header": bool(cell.column_header or cell.row_header)}
                for r in range(r0, r1):
                    for c in range(c0, c1):
                        if rows[r][c] is not None:
                            raise ReadError("Docling devolvió celdas superpuestas")
                        rows[r][c] = value
            tables.append({"index": index, "bbox": _box(table.prov[0].bbox, height),
                           "rows": rows, "docling_ref": table.self_ref})
        text = doc.export_to_text(page_no=number, traverse_pictures=True)
        if not text.strip():
            result["warnings"].append(f"Página {number}: sin texto extraíble")
        if not tables:
            result["warnings"].append(f"Página {number}: sin tablas detectadas")
        result["pages"].append({"number": number, "text": text, "tables": tables})
    return result
