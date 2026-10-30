"""Contenidos de prueba armados a mano, con la forma esperable de cada sitio.

No son respuestas reales del BCU ni del BCP.
"""
import json

import pytest

from leip_tools import MONTH_YEAR_PATTERN, ContentError, extract_links

BASE = "https://www.bcu.gub.uy/Paginas/listado.aspx"

LISTADO_BCU = """
<html><body>
<ul class="documentos">
  <li><a href="/Expectativas/Informe%20expectativas%20de%20mercado%20SETIEMBRE%202026.pdf">Informe expectativas de mercado SETIEMBRE 2026</a>
      <span class="fecha">15/09/2026</span></li>
  <li><a href="/Expectativas/Informe%20expectativas%20de%20mercado%20AGOSTO%202026.pdf">Informe expectativas de mercado AGOSTO 2026</a></li>
  <li><a href="/Expectativas/IEES05I2.csv">Histórico de expectativas de inflación (CSV)</a></li>
  <li><a href="/Expectativas/IEES05I2.xlsx">Histórico de expectativas de inflación (Excel)</a></li>
  <li><a href="/Paginas/Monitor-setiembre-2026.aspx">Monitor para la inflación y la economía - Setiembre 2026</a></li>
  <li><a href="Monitor-agosto-2026.aspx">Monitor para la inflación y la economía - Agosto 2026</a></li>
  <li><a href="/Expectativas/Informe%20expectativas%20de%20mercado%20SETIEMBRE%202026.pdf">duplicado</a></li>
  <li><a href="#">volver</a> <a href="javascript:void(0)">imprimir</a></li>
</ul>
</body></html>
"""


def test_operadores_url_absoluta_y_referencia():
    links = extract_links(LISTADO_BCU, BASE, {"filters": [{"on": "url", "extension": ".pdf"}]})
    assert len(links) == 2  # sin duplicados
    assert links[0].url == "https://www.bcu.gub.uy/Expectativas/Informe%20expectativas%20de%20mercado%20SETIEMBRE%202026.pdf"
    assert links[0].text == "Informe expectativas de mercado SETIEMBRE 2026"
    assert links[0].source_ref == "item[0] ul > li:nth-of-type(1) > a"


def test_no_inventa_fechas_si_no_estan_configuradas():
    links = extract_links(LISTADO_BCU, BASE, {"filters": [{"on": "url", "extension": ".pdf"}]})
    assert links[0].metadata == {}


def test_fecha_configurada_desde_el_item_o_desde_el_texto():
    config = {
        "item_selector": "li",
        "link_selector": "a[href]",
        "metadata": {
            "publicado": {"selector": ".fecha", "type": "date", "formats": ["%d/%m/%Y"]},
            "edicion": {"from": "text", "type": "date", "pattern": MONTH_YEAR_PATTERN},
        },
        "filters": [{"on": "url", "extension": [".pdf"]}],
    }
    a, b = extract_links(LISTADO_BCU, BASE, config)
    assert a.metadata == {"publicado": "2026-09-15", "publicado_raw": "15/09/2026",
                          "edicion": "2026-09", "edicion_raw": a.text}
    assert b.metadata["publicado"] is None and b.metadata["edicion"] == "2026-08"


def test_historico_por_nombre_de_archivo():
    config = {"filters": [{"on": "filename", "equals": "IEES05I2.csv"}]}
    links = extract_links(LISTADO_BCU, BASE, config)
    assert [l.url for l in links] == ["https://www.bcu.gub.uy/Expectativas/IEES05I2.csv"]


def test_monitor_filtros_combinados_y_relativos():
    config = {"filters": [{"on": "text", "contains": "monitor"}, {"on": "url", "extension": ".aspx"}]}
    links = extract_links(LISTADO_BCU, BASE, config)
    assert links[1].url == "https://www.bcu.gub.uy/Paginas/Monitor-agosto-2026.aspx"


def test_exclude():
    config = {"filters": [{"on": "url", "extension": ".pdf"}, {"on": "text", "contains": "agosto", "exclude": True}]}
    assert len(extract_links(LISTADO_BCU, BASE, config)) == 1


# --- Paraguay: extract_links dos veces, cambiando solo la configuración ---

HISTORICO_PY = """
<div class="listado">
  <article class="edicion"><h3>Encuesta de Expectativas de Variables Económicas - Setiembre 2026</h3>
    <p>Resumen...</p><a href="/eev/setiembre-2026">Ver más</a></article>
  <article class="edicion"><h3>Encuesta de Expectativas de Variables Económicas - Agosto 2026</h3>
    <a href="/eev/agosto-2026">Ver más</a></article>
  <a href="/contacto">Contacto</a>
</div>
"""

EDICION_PY = """
<main>
  <a href="/eev/setiembre-2026/anexo.xlsx">Anexo</a>
  <a href="/documents/20117/EEV-setiembre-2026.pdf" title="Informe EEV">Informe</a>
  <a href="/eev">Volver</a>
</main>
"""


def test_paraguay_paso_2_ediciones_con_titulo_y_ver_mas():
    config = {
        "item_selector": "article.edicion",
        "link_selector": "a:-soup-contains('Ver más')",
        "metadata": {"titulo": {"selector": "h3"}},
    }
    links = extract_links(HISTORICO_PY, "https://www.bcp.gov.py/eev", config)
    assert [l.url for l in links] == ["https://www.bcp.gov.py/eev/setiembre-2026", "https://www.bcp.gov.py/eev/agosto-2026"]
    assert links[0].metadata["titulo"].endswith("Setiembre 2026")


def test_paraguay_paso_4_enlace_informe_con_pdf():
    config = {"filters": [{"on": "text", "equals": "Informe"}, {"on": "url", "extension": ".pdf"}],
              "metadata": {"titulo": {"attr": "title"}}}
    links = extract_links(EDICION_PY, "https://www.bcp.gov.py/eev/setiembre-2026", config)
    assert len(links) == 1
    assert links[0].url == "https://www.bcp.gov.py/documents/20117/EEV-setiembre-2026.pdf"
    assert links[0].metadata == {"titulo": "Informe EEV"}


# --- JSON ---

LISTADO_JSON = {
    "Row": [
        {"FileRef": "/Expectativas/Informe expectativas de mercado SETIEMBRE 2026.pdf",
         "FileLeafRef": "Informe expectativas de mercado SETIEMBRE 2026.pdf",
         "Created": "2026-09-15T13:00:00Z", "ID": 41},
        {"FileRef": "/Expectativas/IEES05I2.csv", "FileLeafRef": "IEES05I2.csv",
         "Created": "2026-10-02T10:00:00Z", "ID": 7},
    ]
}


def test_json_con_metadatos_y_filtro_sobre_metadato():
    config = {
        "items_path": "Row",
        "url_field": "FileRef",
        "metadata": {
            "nombre": {"field": "FileLeafRef"},
            "creado": {"field": "Created", "type": "date", "formats": ["%Y-%m-%dT%H:%M:%SZ"]},
            "id": {"field": "ID"},
        },
        "filters": [{"on": "nombre", "pattern": r"\.pdf$"}],
    }
    links = extract_links(LISTADO_JSON, BASE, config)
    assert len(links) == 1
    assert links[0].text is None
    assert links[0].metadata["creado"] == "2026-09-15" and links[0].metadata["id"] == "41"
    assert links[0].source_ref == "Row[0]"


def test_json_como_texto_se_detecta_solo():
    config = {"items_path": "Row", "url_field": "FileRef", "filters": [{"on": "filename", "contains": "iees05i2"}]}
    links = extract_links(json.dumps(LISTADO_JSON), BASE, config)
    assert links[0].url == "https://www.bcu.gub.uy/Expectativas/IEES05I2.csv"


def test_json_que_trae_html_adentro():
    data = {"d": {"html": LISTADO_BCU}}
    links = extract_links(data, BASE, {"html_path": "d.html", "filters": [{"on": "url", "extension": ".csv"}]})
    assert len(links) == 1


def test_metadato_con_pattern_y_grupo_value():
    config = {"metadata": {"anio": {"from": "url", "pattern": r"-(?P<value>\d{4})\.aspx"}},
              "filters": [{"on": "url", "extension": ".aspx"}]}
    assert extract_links(LISTADO_BCU, BASE, config)[0].metadata == {"anio": "2026"}


def test_sin_resultados_es_error_de_contenido():
    with pytest.raises(ContentError) as e:
        extract_links(LISTADO_BCU, BASE, {"filters": [{"on": "url", "extension": ".zip"}]})
    assert e.value.details["candidates"] > 0


def test_min_results_cero():
    assert extract_links("<html></html>", BASE, {"min_results": 0}) == []


def test_items_path_incorrecto():
    with pytest.raises(ContentError):
        extract_links(LISTADO_JSON, BASE, {"items_path": "Rows", "url_field": "FileRef"})
