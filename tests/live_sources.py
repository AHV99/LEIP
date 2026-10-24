"""Soporte de pruebas de red. No forma parte de las tools instaladas.

Siempre hace solicitudes reales. Guarda respuestas y trazas para auditoría;
no acepta fixtures locales ni sustituye errores por contenido de ejemplo.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urljoin, urlsplit, unquote
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "config/fuentes_prueba.json").read_text(encoding="utf-8"))["banks"]


class LiveSources:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cache = {}
        self.trace = {"started_at": datetime.now(timezone.utc).isoformat(), "requests": [], "checks": []}
        self.save()

    def save(self):
        (self.directory / "sources.json").write_text(
            json.dumps(self.trace, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(self, name, details):
        self.trace["checks"].append({"name": name, **details})
        self.save()

    def fetch(self, url, *, form=None):
        body = urlencode(form).encode("utf-8") if form is not None else None
        key = (url, body)
        if key in self.cache:
            return self.cache[key]
        record = {"url": url, "method": "POST" if body is not None else "GET",
                  "requested_at": datetime.now(timezone.utc).isoformat()}
        if form is not None:
            record["form"] = form
        request = Request(quote(url, safe=":/%?=&+"), data=body,
                          headers={"User-Agent": "LEIP-real-reader-tests/0.1"})
        try:
            with urlopen(request, timeout=40) as response:
                content = response.read()
                record.update(status=response.status, final_url=response.url,
                              content_type=response.headers.get("Content-Type"),
                              bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
        except Exception as exc:
            record.update(error=str(exc), status=exc.code if isinstance(exc, HTTPError) else None)
            self.trace["requests"].append(record)
            self.save()
            raise
        number = len(self.trace["requests"]) + 1
        suffix = Path(unquote(urlsplit(url).path)).suffix
        if suffix.lower() not in (".pdf", ".csv", ".xlsx", ".html", ".aspx"):
            suffix = ".json" if "json" in (record["content_type"] or "") else ".html"
        filename = f"{number:02d}{suffix}"
        (self.directory / filename).write_bytes(content)
        record["file"] = filename
        self.trace["requests"].append(record)
        self.cache[key] = content
        self.save()
        return content

    def discover_bcu(self):
        entry = CATALOG["BCU"]["entry_url"]
        page = self.fetch(entry).decode("utf-8")
        configs = re.findall(
            r"d.siteUrl\s*=\s*'([^']+)';\s*d.libraryName\s*=\s*'([^']+)';\s*d.viewName\s*=\s*'([^']+)';", page)
        handler = re.search(r"url:\s*'([^']*BCUDocumentosHandler\.ashx)'", page)
        if not handler or not configs:
            raise AssertionError("La página BCU cambió: no se encuentran handler o parámetros de listados")
        publications = []
        for site, library, view in configs:
            if view not in ("HTML", "Publicar"):
                continue
            start, total = 0, 1
            while start < total:
                form = {"siteUrl": site, "libraryName": library, "viewName": view,
                        "draw": 1, "start": start, "length": 100}
                payload = json.loads(self.fetch(urljoin(entry, handler[1]), form=form))
                total = int(payload["recordsFiltered"])
                rows = payload["data"]
                if not rows and start < total:
                    raise AssertionError("Listado BCU incompleto")
                for row in rows:
                    url = row["DT_RowAttr"]["data-href"]
                    if urlsplit(url).hostname != "www.bcu.gub.uy":
                        raise AssertionError(f"Enlace fuera del BCU: {url}")
                    publications.append({"url": url, "view": view, "metadata": row,
                                         "filename": unquote(urlsplit(url).path.rsplit("/", 1)[-1])})
                start += len(rows)
        names = {p["filename"] for p in publications}
        missing = set(CATALOG["BCU"]["regression_files"]) - names
        if missing:
            raise AssertionError(f"Publicaciones esperadas ausentes en la página BCU: {sorted(missing)}")
        self.check("bcu_discovery", {"entry_url": entry, "publications": publications})
        return publications

    def bcrp_results_url(self):
        config = CATALOG["BCRP"]
        soup = BeautifulSoup(self.fetch(config["entry_url"]), "html.parser")
        link = next((a for a in soup.select("a[href]")
                     if f'/resultados/{config["series_code"]}/html' in a["href"]), None)
        if link is None:
            raise AssertionError("No se encuentra el enlace de la serie en la página BCRP")
        url = urljoin(config["entry_url"], link["href"])
        if urlsplit(url).hostname != "estadisticas.bcrp.gob.pe":
            raise AssertionError("El enlace de resultados sale del dominio oficial BCRP")
        return url
