"""Herramienta 2: extract_links.

Extrae enlaces y sus metadatos de un HTML o JSON según la configuración.
Sirve para publicaciones, archivos y páginas intermedias: en Uruguay saca el
PDF, el CSV o la página de cada edición del listado del BCU; en Paraguay se
usa dos veces, primero para el título y el enlace «Ver más» de cada edición y
después para el enlace «Informe» de la página de la edición.

Devuelve una lista de enlaces con URL absoluta, los metadatos que encuentre y
la referencia de dónde se extrajo cada uno.

No abre los enlaces ni descarga (eso lo hace http_request), no decide qué
publicación falta procesar (eso lo hace el ejecutor) y no inventa fechas:
solo devuelve las que encuentre, si están configuradas.

Configuración:

    format          "html", "json" o "auto" (por defecto "auto")

    Localización
    item_selector   HTML: selector CSS de cada elemento (por defecto "a[href]")
    link_selector   HTML: selector del enlace dentro del elemento, si el
                    elemento no es el enlace (ej. "a:-soup-contains('Ver más')")
    items_path      JSON: ruta con puntos a la lista de ítems (ej. "d.results")
    html_path       JSON: ruta a un campo que trae HTML; ese HTML se procesa
                    con la configuración HTML

    Extracción
    url_attr        HTML: atributo con la URL (por defecto "href")
    url_field       JSON: campo con la URL
    metadata        {nombre: regla}. Cada regla dice de dónde sale el valor:
                      {"selector": ".fecha"}          texto de un elemento del ítem
                      {"selector": "time", "attr": "datetime"}
                      {"attr": "title"}               atributo del enlace
                      {"field": "Created"}            campo del ítem JSON
                      {"from": "text"}                texto del enlace, "url",
                                                      "filename" u otro metadato
                    y opcionalmente:
                      "pattern": regex; se queda con el grupo "value" si
                                 existe, si no con todo lo que coincidió
                      "type": "date"; normaliza a ISO ("2026-09-15", o
                              "2026-09" si solo hay mes). Usa "formats"
                              (strptime) o un "pattern" con grupos year,
                              month (número o nombre en español) y day.
                              Guarda el texto original en <nombre>_raw.

    Filtros         lista de reglas; un enlace pasa si cumple todas
                      {"on": "text", "contains": "Informe"}
                      {"on": "url", "extension": [".pdf"]}
                      {"on": "filename", "pattern": "IEES05I2"}
                      {"on": "title", "pattern": "(?i)monitor", "exclude": true}
                    "on" puede ser text, url, filename o un metadato.
                    "contains" no distingue mayúsculas salvo "case_sensitive": true.

    min_results     mínimo de enlaces esperados (por defecto 1). Si salen
                    menos, lanza ContentError: el contenido cambió de forma.
"""
from __future__ import annotations

import json as jsonlib
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .errors import ContentError

TOOL = "extract_links"

MONTHS_ES = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "set": 9, "sept": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS_ES, key=len, reverse=True))

# Patrón listo para usar en la configuración: "Setiembre 2026", "junio-2026", "mayo de 2026".
MONTH_YEAR_PATTERN = rf"(?i)\b(?P<month>{_MONTH_ALT})\b[\s_\-.]*(?:de[\s_\-]+)?(?P<year>(?:19|20)\d{{2}})\b"

SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "data:")


@dataclass
class Link:
    url: str  # absoluta
    text: str | None  # texto del enlace (HTML); None en JSON
    metadata: dict[str, Any]
    source_ref: str  # dónde se extrajo: "item[3] li:nth-of-type(4) > a" o "results[3]"

    def to_dict(self) -> dict:
        return asdict(self)


def extract_links(
    content: str | bytes | dict | list,
    base_url: str,
    config: dict[str, Any],
    *,
    content_type: str | None = None,
) -> list[Link]:
    """Extrae los enlaces del contenido.

    content: HTML o JSON (texto, bytes o ya parseado), por ejemplo HttpResult.text.
    base_url: URL contra la que se resuelven los enlaces relativos;
        normalmente HttpResult.final_url.
    content_type: el de la respuesta HTTP; ayuda a detectar el formato.
    """
    fmt = _detect_format(content, config.get("format", "auto"), content_type)

    if fmt == "json":
        data = _load_json(content)
        if config.get("html_path"):
            html = _get_path(data, config["html_path"])
            if not isinstance(html, str):
                raise ContentError(f"html_path '{config['html_path']}' no apunta a un texto", tool=TOOL)
            candidates = _from_html(html, config)
        else:
            candidates = _from_json(data, config)
    else:
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
        candidates = _from_html(text, config)

    links: list[Link] = []
    seen: set[str] = set()
    for c in candidates:
        href = (c["href"] or "").strip()
        if not href or href.startswith("#") or href.lower().startswith(SKIP_SCHEMES):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        metadata = _derive_metadata(c["metadata"], c["text"], url, config.get("metadata", {}))
        if not all(_passes(f, c["text"], url, metadata) for f in config.get("filters", [])):
            continue
        seen.add(url)
        links.append(Link(url=url, text=c["text"], metadata=metadata, source_ref=c["ref"]))

    min_results = config.get("min_results", 1)
    if len(links) < min_results:
        raise ContentError(
            f"Se extrajeron {len(links)} enlaces y se esperaban al menos {min_results}",
            tool=TOOL,
            details={"format": fmt, "candidates": len(candidates), "config": config},
        )
    return links


# --- Formato -----------------------------------------------------------------


def _detect_format(content, fmt: str, content_type: str | None) -> str:
    if fmt in ("html", "json"):
        return fmt
    if isinstance(content, (dict, list)):
        return "json"
    if content_type and "json" in content_type:
        return "json"
    head = (content[:200].decode("utf-8", "replace") if isinstance(content, bytes) else content[:200]).lstrip()
    return "json" if head[:1] in ("{", "[") else "html"


def _load_json(content):
    if isinstance(content, (dict, list)):
        return content
    try:
        return jsonlib.loads(content)
    except ValueError as e:
        raise ContentError(f"El contenido no es un JSON válido: {e}", tool=TOOL) from e


# --- HTML --------------------------------------------------------------------


def _from_html(html: str, config: dict) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    url_attr = config.get("url_attr", "href")
    rules = config.get("metadata", {})
    out = []
    for i, item in enumerate(soup.select(config.get("item_selector", "a[href]"))):
        link = item.select_one(config["link_selector"]) if config.get("link_selector") else item
        if link is None:
            continue
        metadata = {}
        for name, rule in rules.items():
            if "selector" in rule or "attr" in rule:
                el = item.select_one(rule["selector"]) if rule.get("selector") else link
                if el is not None:
                    metadata[name] = el.get(rule["attr"]) if rule.get("attr") else _text(el)
                else:
                    metadata[name] = None
        out.append(
            {
                "href": link.get(url_attr),
                "text": _text(link),
                "metadata": metadata,
                "ref": f"item[{i}] {_css_path(link)}",
            }
        )
    return out


def _text(el: Tag | None) -> str:
    return " ".join(el.get_text(" ").split()) if el is not None else ""


def _css_path(el: Tag, depth: int = 4) -> str:
    """Ruta CSS corta del enlace, para que el investigador lo encuentre en la página."""
    parts = []
    while el is not None and el.name not in (None, "[document]", "html", "body") and len(parts) < depth:
        if el.get("id"):
            parts.append(f"{el.name}#{el['id']}")
            break
        siblings = [s for s in el.parent.find_all(el.name, recursive=False)] if el.parent else [el]
        nth = siblings.index(el) + 1 if len(siblings) > 1 else 0
        parts.append(f"{el.name}:nth-of-type({nth})" if nth else el.name)
        el = el.parent
    return " > ".join(reversed(parts))


# --- JSON --------------------------------------------------------------------


def _from_json(data, config: dict) -> list[dict]:
    if "url_field" not in config:
        raise ValueError("Para JSON hace falta url_field en la configuración")
    path = config.get("items_path", "")
    items = _get_path(data, path) if path else data
    if not isinstance(items, list):
        raise ContentError(
            f"items_path '{path}' no apunta a una lista", tool=TOOL, details={"type": type(items).__name__}
        )
    label = path.split(".")[-1] if path else "items"
    rules = config.get("metadata", {})
    out = []
    for i, item in enumerate(items):
        href = _get_path(item, config["url_field"])
        metadata = {name: _get_path(item, r["field"]) for name, r in rules.items() if "field" in r}
        out.append(
            {"href": str(href) if href is not None else "", "text": None, "metadata": metadata, "ref": f"{label}[{i}]"}
        )
    return out


def _get_path(data, path: str):
    """Ruta con puntos: "d.results", "Row.0.FileRef". Devuelve None si no existe."""
    cur = data
    for key in path.split("."):
        if isinstance(cur, list) and key.isdigit():
            idx = int(key)
            cur = cur[idx] if idx < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
        if cur is None:
            return None
    return cur


# --- Metadatos ---------------------------------------------------------------


def _filename(url: str) -> str:
    return unquote(os.path.basename(urlparse(url).path))


def _field_value(name: str, text, url: str, metadata: dict):
    if name == "text":
        return text
    if name == "url":
        return unquote(url)
    if name == "filename":
        return _filename(url)
    return metadata.get(name)


def _derive_metadata(raw: dict, text, url: str, rules: dict) -> dict:
    """Completa los metadatos "from" y aplica pattern y type, en el orden de la configuración."""
    out: dict[str, Any] = {}
    for name, rule in rules.items():
        if "from" in rule:
            value = _field_value(rule["from"], text, url, out)
        else:
            value = raw.get(name)
        if value is not None and not isinstance(value, str):
            value = str(value)

        if rule.get("type") == "date":
            out[f"{name}_raw"] = value
            out[name] = _parse_date(value, rule) if value else None
            continue

        if value and rule.get("pattern"):
            m = re.search(rule["pattern"], value)
            value = (m.group("value") if "value" in m.re.groupindex else m.group(0)) if m else None
        out[name] = value
    return out


def _parse_date(value: str, rule: dict) -> str | None:
    for fmt in rule.get("formats", []):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    if not rule.get("pattern"):
        return None
    m = re.search(rule["pattern"], value)
    if not m:
        return None
    g = m.groupdict()
    year, month, day = g.get("year"), g.get("month"), g.get("day")
    if not year:
        return None
    if month is None:
        return year
    month_num = int(month) if month.isdigit() else MONTHS_ES.get(month.lower())
    if not month_num or not 1 <= month_num <= 12:
        return None
    if day:
        return f"{int(year):04d}-{month_num:02d}-{int(day):02d}"
    return f"{int(year):04d}-{month_num:02d}"


# --- Filtros -----------------------------------------------------------------


def _passes(rule: dict, text, url: str, metadata: dict) -> bool:
    value = _field_value(rule.get("on", "text"), text, url, metadata)
    value = "" if value is None else str(value)
    ok = True
    if "contains" in rule:
        needle = rule["contains"]
        ok = needle in value if rule.get("case_sensitive") else needle.lower() in value.lower()
    if ok and "pattern" in rule:
        ok = re.search(rule["pattern"], value) is not None
    if ok and "equals" in rule:
        ok = value == rule["equals"]
    if ok and "extension" in rule:
        exts = rule["extension"] if isinstance(rule["extension"], list) else [rule["extension"]]
        target = urlparse(value).path if rule.get("on", "text") == "url" else value
        ok = os.path.splitext(target)[1].lower() in [e.lower() for e in exts]
    return not ok if rule.get("exclude") else ok
