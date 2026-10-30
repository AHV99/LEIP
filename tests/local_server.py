"""Servidor HTTP local para las pruebas de http_request y de los recorridos. No toca fuentes reales."""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from tests.test_readers import pdf_fixture

STATE = {"flaky": 0}

LISTADO_BCU = """
<ul>
  <li><a href="/bcu/Informe%20expectativas%20de%20mercado%20SETIEMBRE%202026.pdf">Informe expectativas de mercado SETIEMBRE 2026</a></li>
  <li><a href="/bcu/IEES05I2.csv">Histórico de expectativas de inflación</a></li>
  <li><a href="/bcu/Monitor_trimestral_set26.html">Monitor para la inflación y la economía - Setiembre 2026</a></li>
</ul>
"""
MONITOR = "<h2>Inflación</h2><table><tr><th>Horizonte</th><th>Mediana</th></tr><tr><td>2026</td><td>4,7</td></tr></table>"
HISTORICO_PY = """
<article class="edicion"><h3>Encuesta de Expectativas - Octubre 2026</h3><a href="/py/octubre-2026">Ver más</a></article>
<a href="/contacto">Contacto</a>
"""
EDICION_PY = '<a href="/py/anexo.xlsx">Anexo</a><a href="/py/Informe_EVE-octubre_2026.pdf">Informe</a>'
PDF_PATHS = ("/bcu/Informe%20expectativas%20de%20mercado%20SETIEMBRE%202026.pdf", "/py/Informe_EVE-octubre_2026.pdf")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body: bytes, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/pagina":
            self._send(200, "<html><body>Expectativas de los agentes</body></html>".encode(), "text/html; charset=utf-8")
        elif u.path == "/eco":
            self._send(200, json.dumps({"q": q, "ua": self.headers["User-Agent"]}).encode(), "application/json")
        elif u.path == "/redirige":
            self.send_response(302)
            self.send_header("Location", "/pagina")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif u.path == "/informe":
            body = b"%PDF-1.4 contenido de prueba"
            self._send(200, body, "application/pdf",
                       {"Content-Disposition": 'attachment; filename="Informe expectativas de mercado SETIEMBRE 2026.pdf"'})
        elif u.path in ("/datos/IEES05I2.csv", "/bcu/IEES05I2.csv"):
            self._send(200, b'"fecha","infla_12m_median"\n"2026-09-01",4.7\n', "text/csv")
        elif u.path in PDF_PATHS:
            self._send(200, pdf_fixture(), "application/pdf")
        elif u.path == "/bcu/Monitor_trimestral_set26.html":
            self._send(200, MONITOR.encode(), "text/html; charset=utf-8")
        elif u.path == "/py/historico":
            self._send(200, HISTORICO_PY.encode(), "text/html; charset=utf-8")
        elif u.path == "/py/octubre-2026":
            self._send(200, EDICION_PY.encode(), "text/html; charset=utf-8")
        elif u.path == "/latin1":
            self._send(200, "Público".encode("latin-1"), "text/html")
        elif u.path == "/grande":
            self._send(200, b"x" * 5000, "application/octet-stream")
        elif u.path == "/no-existe":
            self._send(404, b"no encontrado", "text/html")
        elif u.path == "/inestable":
            STATE["flaky"] += 1
            if STATE["flaky"] < 2:
                self._send(503, b"ocupado", "text/plain")
            else:
                self._send(200, b"ok", "text/plain")
        else:
            self._send(404, b"", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode()
        if urlparse(self.path).path == "/bcu/listado":
            self._send(200, LISTADO_BCU.encode(), "text/html; charset=utf-8")
            return
        form = {k: v[0] for k, v in parse_qs(body).items()}
        self._send(200, json.dumps({"form": form, "ctype": self.headers["Content-Type"],
                                    "cookie": self.headers.get("Cookie")}).encode(), "application/json")
