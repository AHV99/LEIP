"""Comprobación puntual de Docling sobre un informe real del BCU."""
import json

import pytest

from leip_tools import read_pdf
from tests.live_sources import ROOT, CATALOG
from tests.test_bcu import PDF

pytestmark = [pytest.mark.bcu, pytest.mark.docling]


def test_docling_bcu_real_pdf(bcu_download, live_sources, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(ROOT / "work/models/huggingface"))
    monkeypatch.setenv("DOCLING_CACHE_DIR", str(ROOT / "work/models/docling"))
    result = read_pdf(bcu_download("bcu-operadores.pdf", PDF), source=PDF,
                      **CATALOG["BCU"]["docling_pdf_options"])
    (live_sources.directory / "docling-bcu.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    page = result["pages"][0]
    assert result["backend"] == "docling"
    assert len(page["tables"]) >= 2
    # Se comprueban ambas medianas en la misma fila, sin fijar coordenadas.
    median_rows = [row for table in page["tables"] for row in table["rows"]
                   if any(c and c["value"] and "Mediana" in c["value"] for c in row)]
    assert any(all(value in [c["value"] for c in row if c] for value in ("0,35%", "4,75%", "4,60%"))
               for row in median_rows)
    assert any(all(value in [c["value"] for c in row if c] for value in ("5,75%", "6,50%"))
               for row in median_rows)
    assert all(c["ref"]["source"] == PDF and c["ref"]["page"] == 1
               for row in median_rows for c in row if c)
    live_sources.check("docling_bcu_pdf", {"version": result["backend_version"],
                                          "tables": len(page["tables"]), "ocr": result["ocr"],
                                          "output": "docling-bcu.json"})
