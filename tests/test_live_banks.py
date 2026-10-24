"""Pruebas adicionales con contenido que proviene de bancos centrales reales."""
import json

from bs4 import BeautifulSoup
import pytest

from leip_tools import read_html, read_pdf
from tests.live_sources import CATALOG

pytestmark = pytest.mark.live


def test_bcb_entry_page_and_real_focus_pdf(live_sources):
    bank = CATALOG["BCB"]
    page = BeautifulSoup(live_sources.fetch(bank["entry_url"]), "html.parser")
    assert page.title and "Banco Central do Brasil" in page.title.get_text()
    data = live_sources.fetch(bank["sample_url"])
    assert data.startswith(b"%PDF"), "La descarga no es un PDF"
    result = read_pdf(data, source=bank["sample_url"], pages=[1])
    first = result["pages"][0]
    assert "30 de abril de 2026" in first["text"]
    rows = [r for table in first["tables"] for r in table["rows"]]
    ipca = next(r for r in rows if r[0]["value"] == "IPCA (variação %)")
    selic = next(r for r in rows if r[0]["value"] == "Selic (% a.a)")
    # Columnas: indicador, hace cuatro semanas, hace una semana, hoy (2026).
    assert [c["value"] for c in ipca[1:4]] == ["4,36", "4,86", "4,89"]
    assert selic[3]["value"] == "13,00"
    assert ipca[3]["ref"]["source"] == bank["sample_url"]
    assert ipca[3]["ref"]["page"] == 1
    assert ipca[3]["ref"]["bbox"]
    json.dumps(result)
    live_sources.check("bcb_focus_pdf", {"period": bank["sample_period"],
                                        "ipca_2026_today": ipca[3]["value"],
                                        "selic_2026_today": selic[3]["value"],
                                        "tables": len(first["tables"]),
                                        "discovery": "Informe histórico configurado; listado dinámico aún no automatizado"})


def test_bcrp_follow_official_series_link_and_read_html(live_sources):
    bank = CATALOG["BCRP"]
    url = live_sources.bcrp_results_url()
    result = read_html(live_sources.fetch(url), source=url,
                       table_selector=bank["table_selector"],
                       sections=["Expectativa de Inflación a 12 meses"])
    assert len(result["tables"]) == 1
    rows = result["tables"][0]["rows"]
    # Tabla de datos dentro de la tabla que el sitio usa para su diseño.
    assert len(rows) > 280
    january = next(r for r in rows if r[0] and r[0]["value"] == "Ene02")
    september = next(r for r in rows if r[0] and r[0]["value"] == "Sep26")
    assert january[1]["value"] == "2.10"
    assert september[1]["value"] == "3.09"
    assert september[1]["ref"]["source"] == url
    assert september[1]["ref"]["section"] == "Expectativa de Inflación a 12 meses"
    json.dumps(result)
    live_sources.check("bcrp_html", {"series": bank["series_code"], "url": url,
                                    "rows": len(rows), "period": "Sep26", "value": september[1]["value"]})
