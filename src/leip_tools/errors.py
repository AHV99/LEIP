"""Errores de las herramientas.

Siguen las dos ramas del diagrama del pipeline:

- TechnicalError: la fuente no respondió como se esperaba (red, timeout,
  status HTTP inesperado). El pipeline notifica y no investiga.
- ContentError: la fuente respondió, pero el contenido no coincide con lo que
  dice la configuración (por ejemplo, el listado no trae ninguna publicación).
  El pipeline lo manda a cuarentena e investigación.
"""


class ToolError(Exception):
    kind = "tool"

    def __init__(self, message: str, *, tool: str, details: dict | None = None):
        super().__init__(message)
        self.tool = tool
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"kind": self.kind, "tool": self.tool, "message": str(self), "details": self.details}


class TechnicalError(ToolError):
    kind = "technical"


class ContentError(ToolError):
    kind = "content"
