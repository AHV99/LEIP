import json
import os

import pytest

from leip_tools import TechnicalError, http_request, new_session


def test_get_html_devuelve_texto(server):
    r = http_request(f"{server}/pagina")
    assert r.status == 200 and r.ok
    assert r.content_type == "text/html"
    assert "Expectativas" in r.text
    assert r.file is None


def test_get_con_parametros_y_user_agent(server):
    r = http_request(f"{server}/eco", params={"anio": 2026})
    data = json.loads(r.text)
    assert data["q"] == {"anio": ["2026"]}
    assert data["ua"].startswith("LEIP-motor")


def test_post_con_formulario_como_el_handler_del_bcu(server):
    form = {"siteUrl": "/x", "libraryName": "Docs", "viewName": "Todos"}
    r = http_request(f"{server}/handler", "POST", data=form)
    data = json.loads(r.text)
    assert data["form"] == form
    assert data["ctype"] == "application/x-www-form-urlencoded"
    assert r.request["body"] == {"form": form}


def test_post_json(server):
    r = http_request(f"{server}/api", "POST", json={"a": 1})
    assert json.loads(r.text)["ctype"] == "application/json"


def test_redireccion_informa_url_final(server):
    r = http_request(f"{server}/redirige")
    assert r.final_url == f"{server}/pagina"
    assert r.redirects == [f"{server}/redirige"]


def test_pdf_se_guarda_como_archivo_temporal(server, tmp_path):
    r = http_request(f"{server}/informe", temp_dir=str(tmp_path))
    assert r.text is None
    assert r.file.filename == "Informe expectativas de mercado SETIEMBRE 2026.pdf"
    assert r.file.path.endswith(".pdf") and os.path.dirname(r.file.path) == str(tmp_path)
    with open(r.file.path, "rb") as f:
        assert f.read().startswith(b"%PDF")
    assert r.file.size == 28 and len(r.file.sha256) == 64


def test_csv_como_texto_o_como_archivo(server, tmp_path):
    texto = http_request(f"{server}/datos/IEES05I2.csv")
    assert texto.text.startswith('"fecha"')
    archivo = http_request(f"{server}/datos/IEES05I2.csv", save="always", temp_dir=str(tmp_path))
    assert archivo.file.filename == "IEES05I2.csv"


def test_detecta_latin1(server):
    assert http_request(f"{server}/latin1").text == "Público"


def test_status_inesperado_es_error_tecnico(server):
    with pytest.raises(TechnicalError) as e:
        http_request(f"{server}/no-existe")
    assert e.value.details["status"] == 404
    assert e.value.to_dict()["kind"] == "technical"


def test_status_libre_si_expected_status_es_none(server):
    assert http_request(f"{server}/no-existe", expected_status=None).status == 404


def test_reintenta_ante_5xx(server):
    r = http_request(f"{server}/inestable", backoff=0)
    assert r.text == "ok"


def test_sin_conexion_es_error_tecnico():
    with pytest.raises(TechnicalError):
        http_request("http://127.0.0.1:9/", retries=1, backoff=0, timeout=2)


def test_limite_de_tamano(server, tmp_path):
    with pytest.raises(TechnicalError):
        http_request(f"{server}/grande", max_bytes=1000, temp_dir=str(tmp_path))
    assert os.listdir(tmp_path) == []  # no deja archivos a medias


def test_sesion_compartida(server):
    s = new_session()
    s.cookies.set("ASP.NET_SessionId", "abc")
    r = http_request(f"{server}/handler", "POST", data={"a": "1"}, session=s)
    assert "ASP.NET_SessionId=abc" in json.loads(r.text)["cookie"]
