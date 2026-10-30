from http.server import ThreadingHTTPServer
import json
import threading
from urllib.parse import unquote

import pytest

from tests.live_sources import LiveSources, ROOT
from tests.local_server import Handler


def pytest_addoption(parser):
    parser.addoption("--bcu", action="store_true", help="Descargar y probar fuentes reales BCU")
    parser.addoption("--live", action="store_true", help="Solo integración real: BCU, BCB y BCRP")
    parser.addoption("--docling", action="store_true", help="Habilita la conversión real BCU con Docling")


def pytest_collection_modifyitems(config, items):
    live = config.getoption("--live")
    if live:
        selected = [item for item in items if "bcu" in item.keywords or "live" in item.keywords]
        deselected = [item for item in items if item not in selected]
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
    if not (config.getoption("--bcu") or live):
        for item in items:
            if "bcu" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Usar --bcu para pruebas de red"))
    if not live:
        for item in items:
            if "live" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Usar --live para otros bancos"))
    if not config.getoption("--docling"):
        for item in items:
            if "docling" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Usar --docling; requiere modelos locales"))


@pytest.fixture(scope="session")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="session")
def live_sources():
    from datetime import datetime, timezone
    directory = ROOT / "work/live-checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    client = LiveSources(directory)
    yield client
    (ROOT / "work/live-checks/latest.json").write_text(
        json.dumps({"report": str(directory / "sources.json")}, indent=2), encoding="utf-8")


@pytest.fixture(scope="session")
def bcu_publications(live_sources):
    return live_sources.discover_bcu()


@pytest.fixture(scope="session")
def bcu_download(bcu_publications, live_sources):
    """Comprueba el enlace publicado y descarga su contenido real."""
    def download(name, url):
        publication = next((p for p in bcu_publications if unquote(p["url"]) == unquote(url)), None)
        if publication is None:
            raise AssertionError(f"La URL no está publicada en los listados oficiales del BCU: {url}")
        return live_sources.fetch(publication["url"])
    return download
