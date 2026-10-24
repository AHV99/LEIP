"""Regresión sobre publicaciones BCU verificadas el 23/10/2026.

URLs observadas en el inventario y listado oficial. Las coordenadas del PDF
pertenecen a esta edición y son configuración del test, nunca del lector.
"""
import json
from decimal import Decimal

import pytest

from leip_tools import read_html, read_pdf, read_spreadsheet

pytestmark = pytest.mark.bcu

BASE = "https://www.bcu.gub.uy/Politica-Economica-y-Mercados/"
HTML = BASE + "Expectativas%20para%20la%20inflacin%20y%20la%20economa/Monitor_trimestral_set26.html"
XLSX = BASE + "Expectativas%20para%20la%20inflacin%20y%20la%20economa/IEES05I2.xlsx"
PDF = BASE + "Expectativas%20del%20Mercado/Informe%20expectativas%20de%20mercado%20SETIEMBRE%202026.pdf"
CSV = BASE + "Expectativas%20para%20la%20inflacin%20y%20la%20economa/IEES05I2.csv"


def values(row):
    return [cell["value"] if cell else None for cell in row]


@pytest.fixture(scope="module")
def monitor(bcu_download):
    return read_html(bcu_download("bcu-monitor.html", HTML), source=HTML,
                     sections=["Expectativas de inflación", "Expectativas económicas"])


@pytest.fixture(scope="module")
def historical(bcu_download):
    return read_spreadsheet(bcu_download("IEES05I2.xlsx", XLSX), format="xlsx",
                            source=XLSX, sheet="EVOLUCION", header_row=None)


@pytest.fixture(scope="module")
def csv_historical(bcu_download):
    return read_spreadsheet(bcu_download("IEES05I2.csv", CSV), format="csv", source=CSV,
                            numeric_columns=["infla_12m_median", "infla_24m_median", "infla_mes_median"])


def test_bcu_csv_downloaded_from_official_listing(csv_historical, live_sources):
    result = csv_historical
    assert len(result["columns"]) == 72
    assert len(result["rows"]) >= 273
    index = {name: position for position, name in enumerate(result["columns"])}
    september = next(r for r in result["rows"] if r[index["fecha"]]["value"] == "2026-09-01")
    assert september[index["infla_12m_median"]]["decimal_value"] == "4.6"
    assert september[index["infla_24m_median"]]["decimal_value"] == "4.55"
    assert september[index["infla_trim_mean"]]["value"] is None
    assert september[index["infla_12m_median"]]["ref"]["source"] == CSV
    live_sources.check("bcu_csv", {"rows": len(result["rows"]), "columns": len(result["columns"]),
                                   "period": "2026-09-01", "inflation_12m_median": "4.6",
                                   "inflation_24m_median": "4.55"})


def test_bcu_latest_monitor_matches_live_csv(bcu_publications, live_sources, csv_historical):
    candidates = [p for p in bcu_publications if p["filename"].lower().endswith(".html")
                  and p["view"] == "HTML"]
    latest = max(candidates, key=lambda p: (int(p["metadata"]["2"]), int(p["metadata"]["3"])))
    year, month = int(latest["metadata"]["2"]), int(latest["metadata"]["3"])
    period = f"{year:04d}-{month:02d}-01"
    monitor = read_html(live_sources.fetch(latest["url"]), source=latest["url"],
                        sections=["Expectativas de inflación"])
    medians = next(r for r in monitor["tables"][0]["rows"] if r[0] and r[0]["value"] == "Mediana")
    columns = csv_historical["columns"]
    row = next(r for r in csv_historical["rows"] if r[columns.index("fecha")]["value"] == period)
    names = ["infla_mes_median", "infla_6m_median", "infla_t_median", "infla_12m_median",
             "infla_t1_median", "infla_24m_median", "infla_t2_median"]
    actual = {}
    for position, name in enumerate(names, 1):
        html_value = Decimal(medians[position]["value"].replace(",", "."))
        csv_value = Decimal(row[columns.index(name)]["value"])
        assert abs(html_value-csv_value) <= Decimal("0.005"), (name, html_value, csv_value)
        actual[name] = {"html": str(html_value), "csv": str(csv_value)}
    live_sources.check("bcu_latest_monitor_vs_csv", {"period": period, "url": latest["url"], "values": actual})


def test_bcu_csv_matches_excel(csv_historical, historical):
    columns = csv_historical["columns"]
    csv_row = next(r for r in csv_historical["rows"] if r[columns.index("fecha")]["value"] == "2026-09-01")
    excel_row = next(r for r in historical["rows"] if r[1]["value"] == "Set-26")
    for csv_column, excel_index in [("infla_mes_median", 3), ("infla_t_median", 18), ("infla_12m_median", 23), ("infla_24m_median", 38)]:
        assert Decimal(csv_row[columns.index(csv_column)]["value"]) == Decimal(str(excel_row[excel_index]["value"]))


def test_bcu_html_values_and_merged_cells(monitor):
    assert len(monitor["tables"]) == 2
    table = monitor["tables"][0]
    row = next(r for r in table["rows"] if r[0] and r[0]["value"] == "Mediana")
    assert values(row) == ["Mediana", "0,35", "2,67", "4,70", "4,60", "4,55", "4,55", "4,50", "4,50"]
    assert row[4]["ref"]["source"] == HTML
    assert row[4]["ref"]["section"] == "EXPECTATIVAS DE INFLACIÓN"
    assert table["rows"][0][0]["colspan"] == 9
    assert table["rows"][0][8]["ref"] == table["rows"][0][0]["ref"]
    assert any("Tipo de cambio nominal" == c["value"] for r in monitor["tables"][1]["rows"] for c in r if c)
    json.dumps(monitor)


def test_bcu_xlsx_real_dimensions_dates_and_missing(historical):
    # El archivo declara A1, pero tiene más de 270 meses; no confiar en dimension.
    assert len(historical["rows"]) > 270
    first = next(r for r in historical["rows"] if r[1]["value"] == "2004-01-01T00:00:00")
    assert first[3]["value"] == 1.3
    assert first[3]["ref"]["coordinate"] == "D14"
    assert first[3]["ref"]["sheet"] == "EVOLUCION"
    september = next(r for r in historical["rows"] if r[1]["value"] == "Set-26")
    assert september[18]["value"] == 4.7
    assert september[23]["value"] == 4.6
    assert september[7]["value"] is None
    assert september[23]["ref"]["source"] == XLSX
    json.dumps(historical)


def test_bcu_same_survey_html_and_xlsx(monitor, historical):
    row = next(r for r in historical["rows"] if r[1]["value"] == "Set-26")
    medians = next(r for r in monitor["tables"][0]["rows"] if r[0] and r[0]["value"] == "Mediana")
    assert float(medians[3]["value"].replace(",", ".")) == row[18]["value"]
    assert float(medians[4]["value"].replace(",", ".")) == row[23]["value"]


def test_bcu_pdf_two_tables_values_dates_and_provenance(bcu_download):
    settings = {"vertical_strategy": "explicit", "horizontal_strategy": "text",
                "intersection_x_tolerance": 8}
    boundaries = [45.8, 190.5, 229.7, 271.7, 311, 354.3, 393.5, 437.9, 477.2, 516.4, 555.7, 594.9, 626.4]
    result = read_pdf(bcu_download("bcu-operadores.pdf", PDF), source=PDF, pages=[1], regions={1: [
        {"bbox": [45, 110, 478, 205], "table_settings": {**settings, "explicit_vertical_lines": boundaries[:9]}},
        {"bbox": [45, 230, 627, 286], "table_settings": {**settings, "explicit_vertical_lines": boundaries}},
    ]})
    page = result["pages"][0]
    assert "ENCUESTA DE EXPECTATIVAS DE INFLACIÓN" in page["text"]
    assert len(page["tables"]) == 2
    inflation, tpm = page["tables"]
    row = next(r for r in inflation["rows"] if r[0]["value"] == "1. Mediana")
    assert values(row)[1:] == ["0,35%", "2,70%", "4,75%", "4,60%", "4,60%", "4,58%", "4,50%"]
    assert row[3]["ref"]["page"] == 1
    assert row[3]["ref"]["bbox"] is not None
    assert row[3]["ref"]["source"] == PDF
    rates = next(r for r in tpm["rows"] if r[0]["value"] == "1. Mediana")
    assert values(rates)[1:] == ["5,75%", "6,00%", "6,00%", "6,00%", "6,25%", "6,25%", "6,25%", "6,25%", "6,25%", "6,25%", "6,50%"]
    assert "5/2/2027*" in values(tpm["rows"][0])
    assert "24 MESES" in values(tpm["rows"][0])
    json.dumps(result)
