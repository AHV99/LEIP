"""Los recorridos del documento de herramientas, contra un servidor local.

Comprueban que http_request, extract_links y los lectores encajan entre sí.
No sustituyen las pruebas --live contra las fuentes reales.
"""
import pytest

from leip_tools import extract_links, http_request, new_session, read_html, read_pdf, read_spreadsheet


@pytest.fixture
def descargar(tmp_path):
    session = new_session()

    def run(url):
        return http_request(url, save="always", temp_dir=str(tmp_path), session=session)
    return run


def _listado_bcu(server, filtros):
    listado = http_request(f"{server}/bcu/listado", "POST", data={"libraryName": "Docs"})
    links = extract_links(listado.text, listado.final_url, {"filters": filtros}, content_type=listado.content_type)
    assert len(links) == 1
    return links[0]


def test_uruguay_operadores_pdf(server, descargar):
    link = _listado_bcu(server, [{"on": "url", "extension": ".pdf"}])
    pdf = descargar(link.url)
    result = read_pdf(pdf.file.path, source=pdf.final_url)
    assert result["source"] == link.url
    assert result["pages"][0]["text"] == "Example 4.70"


def test_uruguay_historico_csv(server, descargar):
    link = _listado_bcu(server, [{"on": "filename", "equals": "IEES05I2.csv"}])
    csv = descargar(link.url)
    result = read_spreadsheet(csv.file.path, source=csv.final_url, numeric_columns=["infla_12m_median"])
    assert result["columns"] == ["fecha", "infla_12m_median"]
    cell = result["rows"][0][1]
    assert cell["decimal_value"] == "4.7" and cell["ref"]["coordinate"] == "B2"
    assert cell["ref"]["source"] == link.url


def test_uruguay_monitor_html(server, descargar):
    link = _listado_bcu(server, [{"on": "text", "contains": "monitor"}])
    html = descargar(link.url)
    result = read_html(html.file.path, source=html.final_url, sections=["Inflación"])
    assert result["tables"][0]["rows"][1][1]["value"] == "4,7"


def test_paraguay_dos_veces_extract_links(server, descargar):
    historico = http_request(f"{server}/py/historico")
    ediciones = extract_links(historico.text, historico.final_url, {
        "item_selector": "article.edicion",
        "link_selector": "a:-soup-contains('Ver más')",
        "metadata": {"titulo": {"selector": "h3"}},
    })
    assert ediciones[0].metadata["titulo"].endswith("Octubre 2026")

    edicion = http_request(ediciones[0].url)
    informes = extract_links(edicion.text, edicion.final_url, {
        "filters": [{"on": "text", "equals": "Informe"}, {"on": "url", "extension": ".pdf"}],
    })
    pdf = descargar(informes[0].url)
    assert read_pdf(pdf.file.path, source=pdf.final_url)["pages"][0]["text"] == "Example 4.70"
