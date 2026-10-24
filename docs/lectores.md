# Tools de lectura: primera prueba de concepto

Implementación en `src/leip_tools/readers.py`. Exporta únicamente `read_pdf`,
`read_spreadsheet`, `read_html` y la excepción `ReadError`.

Las funciones reciben una ruta local o bytes y un `source` opcional para
identificar la URL original. No hacen peticiones HTTP, no descubren publicaciones,
no invocan agentes y no asignan significado económico a las celdas.
Los parámetros específicos de cada publicación pertenecen al llamador.

## Qué está construido y por qué se probó

Hay tres funciones reutilizables de lectura. Las pruebas separadas permiten
detectar pérdida de filas, cambios de columna o mezcla de tablas y gráficos
antes de conectar el resto del sistema. No acreditan un flujo completo de LEIP.

Todavía faltan `http_request` y `find_publications` como tools del paquete,
y el ejecutor que combine los pasos. La navegación y descarga existentes están
en el soporte de pruebas; no constituyen esas tools de producción.
Tampoco existe integración con agentes ni interpretación de variables A/B.

## Instalar y probar (PowerShell, desde la raíz del repositorio)

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
.venv\Scripts\python.exe -m pytest -q --live
```

`--live` ejecuta únicamente las nueve pruebas con solicitudes reales: siete BCU,
una BCB y una BCRP. Siempre visita las páginas oficiales y descarga los datos.
No utiliza archivos precargados ni acepta reemplazar una descarga fallida.
Los valores de referencia en los asserts comprueban publicaciones reales;
no se inyectan como entrada de los lectores.

`config/fuentes_prueba.json` registra bancos, páginas de entrada, publicaciones
de regresión y la forma de acceso. El código de navegación está limitado a
`tests/live_sources.py`: no agrega nuevas tools al paquete.

Cada ejecución guarda las respuestas originales en `work/live-checks/<ejecución>/`
y un `sources.json` con hora UTC, URL solicitada y final, método, parámetros POST,
estado HTTP, tipo de contenido, tamaño, SHA-256 y los valores contrastados.
`work/live-checks/latest.json` indica el informe de la última ejecución.
Una descarga fallida queda registrada y hace fallar el test.
No se guardan respuestas reales en Git. Esto no define la política de
almacenamiento del futuro motor.

Las pruebas locales de casos límite se conservan en `tests/test_readers.py` y
se ejecutan con `python -m pytest tests/test_readers.py`. `--live` las excluye.

## Contratos y ejemplos

Todas las posiciones de salida comienzan en 1. Los resultados son diccionarios
serializables con `json.dumps`. `value` conserva el valor leído; `ref` contiene
el origen y la ubicación. Los lectores no redondean, transponen ni interpretan
horizontes. No confundir los operadores del PDF con los analistas del monitor.

### read_spreadsheet

```python
from leip_tools import read_spreadsheet

result = read_spreadsheet(
    "historico.csv", source="URL de origen",
    separator=",", decimal=".", encoding="utf-8-sig",
    header_row=1, numeric_columns=["infla_12m_median"],
)
# result: source, format, sheet, header_row, columns, rows, warnings
# result["rows"][0][0]: {"value": ..., "ref": {...}}
```

- Formatos CSV, XLSX y XLS; para bytes es obligatorio indicar `format`.
- CSV: `separator`, `decimal` y `encoding` explícitos. Los vacíos son `None`;
  un cero se conserva. Las posiciones de fila cuentan registros CSV, no líneas
  físicas (un campo entre comillas puede contener saltos de línea).
- `numeric_columns` agrega `decimal_value`, una cadena decimal exacta, a las
  columnas indicadas. Es opcional; no convierte automáticamente fechas o códigos.
  Admite signo menos Unicode y coma o punto decimal, sin separador de miles.
- XLSX/XLS: `sheet` acepta nombre o índice desde cero. Referencias de hoja,
  fila, columna y coordenada como `D14`. Las fechas Excel se representan en ISO;
  fechas que ya eran texto se conservan como texto.
- `header_row=None` conserva toda la grilla, incluidos encabezados multinivel,
  usando letras de columna como `columns`. Las filas vacías se omiten sin
  renumerar las referencias. Las celdas Excel combinadas conservan valor en su
  celda de origen y vacíos en las restantes, sin inventar encabezados.
- XLSX no calcula fórmulas: devuelve `=...`. XLS devuelve resultados almacenados
  y una advertencia porque xlrd no expone la fórmula original.
- Los números nativos Excel ya tienen precisión binaria; no se promete recuperar
  decimales previos al guardado. La conservación decimal exacta aplica al texto.

Para el archivo actual del BCU:

```python
result = read_spreadsheet("IEES05I2.xlsx", sheet="EVOLUCION", header_row=None)
```

El lector ignora la dimensión declarada del XLSX y recorre las filas reales:
el archivo probado declara `A1` pese a contener cientos de registros.

### read_html

```python
from leip_tools import read_html

result = read_html(
    "monitor.html", source="URL de origen",
    sections=["Expectativas de inflación", "Expectativas económicas"],
)
# result["tables"]: index, section, rows
```

Selecciona por título, no por posición. El título puede ser `caption`, una
primera fila de título con `colspan`, un encabezado h1-h6 precedente o un
`title_selector` CSS explícito dentro de cada tabla. `table_selector` permite
restringir las tablas. `sections` compara texto completo sin distinguir
mayúsculas ni espacios repetidos. Una sección solicitada ausente produce error.

Expande `rowspan` y `colspan` en una grilla rectangular. Las posiciones cubiertas
por una combinación apuntan a la misma referencia de origen; no son observaciones
distintas. Una posición inexistente es `None`; una celda HTML vacía tiene
`value=None` y conserva su referencia. Los signos, unidades y decimales quedan
como texto. Rechaza tablas anidadas o combinaciones inválidas. No ejecuta JavaScript.

### read_pdf

```python
from leip_tools import read_pdf

result = read_pdf("informe.pdf", source="URL de origen", pages=[1])
# result["pages"]: number, text, tables
# cada tabla: index, bbox, rows; cada celda: value, ref
```

Extrae texto completo por página y tablas con coordenadas `bbox` en puntos PDF
`(x0, top, x1, bottom)`. `pages` comienza en 1. `table_settings` admite las
[opciones de pdfplumber](https://github.com/jsvine/pdfplumber#table-extraction-settings).
Sin texto o sin tablas se generan advertencias; no se realiza OCR.

#### Motor Docling

**Estado actual (23/10/2026): validado con Docling 2.142.1.** La conversión del
PDF real de operadores del BCU de septiembre de 2026 detectó dos tablas, sin
coordenadas manuales y sin advertencias de extracción. La tabla de inflación
quedó en 8 filas por 8 columnas y la de TPM en 9 filas por 12 columnas.
Se comprobaron medianas y referencias de origen y página. Esta validación usa
texto nativo, sin OCR, y no acredita todavía documentos escaneados.

Docling se integra como un motor de `read_pdf`, manteniendo las tres tools.
Se instala de manera opcional porque incorpora modelos de reconocimiento de
diseño y tablas, además de PyTorch:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[docling,test]"
.venv\Scripts\python.exe -m pytest tests/test_docling.py --bcu --docling -q
```

También está listo `scripts/probar-docling.ps1`: ejecutar
`.\scripts\probar-docling.ps1`. Para un entorno nuevo admite `-Instalar`.
El script visita el BCU, confirma el enlace del informe, lo descarga y usa
las opciones Docling de `config/fuentes_prueba.json`. Guarda un informe JUnit
en `work/docling-results.xml` y la salida de extracción en la carpeta de la
ejecución correspondiente de `work/live-checks/`.

```python
result = read_pdf("informe.pdf", backend="docling", pages=[1], ocr=False)
```

El motor utiliza detección de diseño y TableFormer en modo ACCURATE. La
primera conversión puede descargar sus modelos. El procesamiento documental
se ejecuta localmente; los documentos no se envían a un LLM remoto.
`artifacts_path` permite indicar modelos ya descargados. Las pruebas guardan
las cachés de modelos en `work/models/huggingface` y `work/models/docling`.

La salida mantiene `source`, `pages`, `text`, `tables`, `rows` y referencias
de celda, y agrega motor, versión y OCR usado. Las celdas combinadas conservan
una misma referencia de origen. Las coordenadas se expresan con origen arriba
a la izquierda. No se redondean valores ni se les asigna significado económico.

Docling no acepta `regions` ni `table_settings`, que pertenecen a pdfplumber.
Las tablas multipágina o las celdas enriquecidas que este adaptador todavía no
puede referenciar con precisión producen un error explícito.
`ocr=True` está disponible, pero necesita su propia validación con documentos
escaneados. La comprobación BCU usa texto nativo y `ocr=False`.

El motor predeterminado sigue siendo pdfplumber para mantener compatibles
las llamadas anteriores. CSV/Excel y HTML conservan sus lectores específicos.
La prueba Docling es opcional y debe habilitarse con `--docling`; sus resultados
no se incluyen dentro de las nueve pruebas reales documentadas anteriormente.

Referencias: [instalación oficial](https://docling-project.github.io/docling/getting_started/installation/)
y [opciones de extracción de tablas](https://github.com/docling-project/docling/blob/main/docs/usage/advanced_options.md).

Si la detección automática mezcla tablas y gráficos, usar `regions`:

```python
result = read_pdf("informe.pdf", pages=[1], regions={1: [
    {"bbox": [45, 110, 478, 205], "table_settings": {
        "vertical_strategy": "explicit",
        "explicit_vertical_lines": [45.8, 190.5, 229.7, 271.7, 311, 354.3, 393.5, 437.9, 477.2],
        "horizontal_strategy": "text", "intersection_x_tolerance": 8,
    }}
]})
```

Estas coordenadas son del PDF de septiembre de 2026. No deben asumirse válidas
para otros informes; las pruebas de regresión comprueban valores y encabezados
conocidos. El texto completo permanece disponible aunque se limiten las regiones.
Los encabezados multilínea pueden ocupar varias filas de tabla; se conserva su
texto, sin fusionarlos mediante interpretación económica.

## Validación con el BCU

Ejecución del 23/10/2026: siete pruebas BCU reales aprobadas. Se visita primero
la página de entrada y se leen sus parámetros `siteUrl`, `libraryName` y
`viewName`, y la ruta al handler. Después se consultan por POST los listados
`HTML` y `Publicar`, incluyendo paginación. Cada enlace de descarga debe aparecer
en esos listados: no se construyen nombres de publicaciones por calendario.
Archivos usados:

- [Monitor de septiembre de 2026 (HTML)](https://www.bcu.gub.uy/Politica-Economica-y-Mercados/Expectativas%20para%20la%20inflacin%20y%20la%20economa/Monitor_trimestral_set26.html):
  dos tablas, ocho medianas de inflación, secciones, celdas combinadas y origen.
- [Histórico de inflación (XLSX)](https://www.bcu.gub.uy/Politica-Economica-y-Mercados/Expectativas%20para%20la%20inflacin%20y%20la%20economa/IEES05I2.xlsx):
  más de 270 registros, dato de enero de 2004, valores de septiembre de 2026,
  vacíos, coordenadas y coincidencia con dos medianas del monitor (4,70 y 4,60).
- [Histórico de inflación (CSV)](https://www.bcu.gub.uy/Politica-Economica-y-Mercados/Expectativas%20para%20la%20inflacin%20y%20la%20economa/IEES05I2.csv):
  274 meses y 72 columnas en la ejecución; se contrastan cuatro medianas con
  Excel y siete con el monitor más reciente encontrado (octubre de 2026).
- [Operadores, septiembre de 2026 (PDF)](https://www.bcu.gub.uy/Politica-Economica-y-Mercados/Expectativas%20del%20Mercado/Informe%20expectativas%20de%20mercado%20SETIEMBRE%202026.pdf):
  dos tablas separadas del gráfico, siete medianas de inflación, once medianas
  de TPM, fecha con asterisco y referencias de página y región.

Los enlaces PDF, CSV y XLSX se verificaron en el listado oficial enlazado desde
[Expectativas de los agentes](https://www.bcu.gub.uy/Politica-Economica-y-Mercados/Paginas/Expectativas-de-los-agentes.aspx).
Corrección respecto a la primera revisión: el CSV sí está publicado, en la vista
`HTML`. Revisar solo la vista `Histórico` había dejado ese enlace fuera.
XLS está implementado, pero no validado con una publicación BCU en esta entrega.

## Pruebas con otros bancos

- **Brasil (BCB):** se visita la página oficial Focus y se descarga un informe
  histórico real del 30/04/2026. El mismo `read_pdf` extrae su tabla, sin reglas
  BCU: IPCA 2026, columna Hoje, 4,89; Selic 2026, columna Hoje, 13,00.
  El informe es una muestra histórica; no se afirma que sea el último disponible.
  La página requiere JavaScript y el descubrimiento automático de sus
  publicaciones sigue pendiente. La URL de muestra se obtuvo del sitio oficial.
- **Perú (BCRP):** se visita la categoría de expectativas, se sigue el enlace de
  resultados de la serie `PD12912AM` y se lee la tabla HTML con `table.series`.
  Se comprueban enero de 2002 (2,10) y septiembre de 2026 (3,09). Esto detectó
  y corrigió un fallo: el lector omitía una tabla seleccionada explícitamente
  cuando estaba dentro de otra tabla usada para el diseño de la página.
- **Paraguay (BCP):** página EVE e informe de octubre de 2026 identificados en
  la web oficial. Python recibió HTTP 403 tanto en la página como en el PDF.
  Está registrado en el catálogo como bloqueado; no se contabiliza como
  extracción validada y no se reemplazan sus datos por una muestra artificial.

Resultado actualizado del 23/10/2026: **10 pruebas reales aprobadas** al ejecutar
`python -m pytest --live --docling -q`. Se registraron 12 solicitudes HTTP, todas
con estado 200. Las **23 pruebas locales** también pasaron en una ejecución
separada. El total es de 33 pruebas aprobadas, sin fallos.
Docling emitió dos avisos de obsolescencia internos de sus dependencias, que no
afectaron la conversión. El modo de red no utiliza mocks.

Informes: `work/live-docling-results.xml`, `work/unit-results.xml` y
`work/live-checks/latest.json`. La carpeta enlazada por este último incluye
`sources.json` (traza de las solicitudes) y `docling-bcu.json` (extracción real).

Las pruebas no demuestran compatibilidad con todos los bancos, todos los diseños
PDF ni futuras ediciones. El alcance del paquete sigue siendo los tres lectores.
La navegación BCU/BCRP y las descargas viven en el soporte de integración;
todavía no hay motor de flujos ni nuevas tools HTTP/discovery en producción.
