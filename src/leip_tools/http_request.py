"""Herramienta 1: http_request.

Hace una consulta GET o POST con parámetros, headers y body. Si se configura,
guarda la respuesta como archivo temporal, así que también cubre la descarga.

Devuelve el status, la URL final (después de redirecciones), el tipo de
contenido y el cuerpo como texto o una referencia al archivo temporal.

En Uruguay se usa para abrir la página de entrada del BCU, hacer el POST al
handler de documentos y descargar el PDF, el CSV y el HTML.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import requests

from .errors import TechnicalError

TOOL = "http_request"

DEFAULT_USER_AGENT = "LEIP-motor/0.1 (proyecto de tesis; extraccion de datos publicos)"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
CHUNK = 64 * 1024

# Tipos que se devuelven como texto cuando save="auto".
TEXT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/javascript",
)

SaveMode = Literal["never", "auto", "always"]


@dataclass
class TempFile:
    """Referencia a la respuesta guardada en disco."""

    path: str
    size: int
    sha256: str
    filename: str  # nombre sugerido por la fuente (Content-Disposition o la URL)


@dataclass
class HttpResult:
    status: int
    final_url: str
    content_type: str  # solo el tipo MIME, sin "; charset=..."
    encoding: str | None
    text: str | None  # cuerpo, si no se guardó como archivo
    file: TempFile | None  # referencia al archivo temporal, si se guardó
    headers: dict[str, str]
    redirects: list[str] = field(default_factory=list)
    request: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = ""
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def to_dict(self) -> dict:
        return asdict(self)


def new_session(user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    """Sesión con cookies compartidas entre pasos.

    Hace falta cuando un sitio exige pasar por la página de entrada antes de
    consultar el servicio, como suele pasar en SharePoint.
    """
    s = requests.Session()
    s.headers["User-Agent"] = user_agent
    return s


def http_request(
    url: str,
    method: str = "GET",
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | str | bytes | None = None,
    json: Any = None,
    save: SaveMode = "auto",
    temp_dir: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    expected_status: tuple[int, ...] | None = (200,),
    retries: int = 2,
    backoff: float = 1.0,
    session: requests.Session | None = None,
) -> HttpResult:
    """Hace la consulta y devuelve un HttpResult.

    data: body de formulario (dict) o crudo (str/bytes). json: body JSON.
    save: "never" devuelve siempre texto, "always" guarda siempre en un
        archivo temporal, "auto" guarda en archivo lo que no es texto
        (PDF, Excel, zip...).
    expected_status: si el status no está en la tupla, lanza TechnicalError.
        None acepta cualquier status y deja que decida quien llama.
    retries: reintentos ante errores de red, timeouts y status 429/5xx.

    Lanza TechnicalError ante errores de red, timeout, respuesta más grande que
    max_bytes o status inesperado.
    """
    method = method.upper()
    if method not in ("GET", "POST"):
        raise ValueError(f"Método no soportado: {method}")
    if data is not None and json is not None:
        raise ValueError("Usar data o json, no los dos")

    sess = session or new_session()
    request_info = {
        "method": method,
        "url": url,
        "params": params,
        "headers": headers,
        "body": _describe_body(data, json),
    }

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(backoff * 2 ** (attempt - 1))
        started = time.monotonic()
        try:
            resp = sess.request(
                method,
                url,
                params=params,
                headers=headers,
                data=data,
                json=json,
                timeout=timeout,
                stream=True,
                allow_redirects=True,
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            last_error = e
            continue
        except requests.RequestException as e:
            raise TechnicalError(f"Error en la consulta: {e}", tool=TOOL, details=request_info) from e

        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < retries:
                resp.close()
                last_error = None
                continue

        try:
            return _build_result(resp, request_info, started, save, temp_dir, max_bytes, expected_status)
        finally:
            resp.close()

    raise TechnicalError(
        f"La fuente no respondió después de {retries + 1} intentos: {last_error}",
        tool=TOOL,
        details=request_info,
    )


def _build_result(resp, request_info, started, save, temp_dir, max_bytes, expected_status) -> HttpResult:
    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    common = dict(
        status=resp.status_code,
        final_url=resp.url,
        content_type=content_type,
        encoding=None,
        text=None,
        file=None,
        headers=dict(resp.headers),
        redirects=[r.url for r in resp.history],
        request=request_info,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    if expected_status is not None and resp.status_code not in expected_status:
        snippet = resp.raw.read(2000, decode_content=True).decode("utf-8", "replace")
        raise TechnicalError(
            f"Status {resp.status_code} inesperado (se esperaba {list(expected_status)})",
            tool=TOOL,
            details={**request_info, "status": resp.status_code, "final_url": resp.url, "body_start": snippet},
        )

    to_file = save == "always" or (save == "auto" and not _is_text(content_type))
    if to_file:
        common["file"] = _stream_to_file(resp, temp_dir, max_bytes, request_info)
    else:
        raw = _read_limited(resp, max_bytes, request_info)
        encoding = resp.encoding or _guess_encoding(raw, content_type)
        common["encoding"] = encoding
        common["text"] = raw.decode(encoding, errors="replace")

    common["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return HttpResult(**common)


def _is_text(content_type: str) -> bool:
    return content_type.startswith(TEXT_TYPES) or content_type.endswith(("+json", "+xml"))


def _guess_encoding(raw: bytes, content_type: str) -> str:
    # requests no adivina el charset de application/json; JSON es UTF-8 por norma.
    if content_type.endswith("json"):
        return "utf-8"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def _read_limited(resp, max_bytes: int, request_info: dict) -> bytes:
    buf = bytearray()
    for chunk in resp.iter_content(CHUNK):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise TechnicalError(
                f"La respuesta supera el máximo de {max_bytes} bytes", tool=TOOL, details=request_info
            )
    return bytes(buf)


def _stream_to_file(resp, temp_dir: str | None, max_bytes: int, request_info: dict) -> TempFile:
    filename = _suggested_filename(resp)
    suffix = os.path.splitext(filename)[1][:10]
    fd, path = tempfile.mkstemp(prefix="leip_", suffix=suffix, dir=temp_dir)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise TechnicalError(
                        f"La descarga supera el máximo de {max_bytes} bytes", tool=TOOL, details=request_info
                    )
                digest.update(chunk)
                f.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    return TempFile(path=path, size=size, sha256=digest.hexdigest(), filename=filename)


def _suggested_filename(resp) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    for part in cd.split(";"):
        part = part.strip()
        if part.lower().startswith("filename*="):
            value = part.split("=", 1)[1].strip('"')
            return unquote(value.split("''", 1)[-1])
        if part.lower().startswith("filename="):
            return part.split("=", 1)[1].strip('"')
    return unquote(os.path.basename(urlparse(resp.url).path)) or "respuesta"


def _describe_body(data, json) -> Any:
    if json is not None:
        return {"json": json}
    if isinstance(data, dict):
        return {"form": data}
    if isinstance(data, (str, bytes)):
        return {"raw_bytes": len(data)}
    return None
