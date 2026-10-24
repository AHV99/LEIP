import io
import json
from zipfile import ZipFile

import pytest

from leip_tools import ReadError, read_html, read_pdf, read_spreadsheet


def test_csv_precision_missing_zero_and_positions():
    source = 'fecha;mediana;n\n2026-09;4,700000000000000001;0\n2026-10;;3\n'.encode()
    result = read_spreadsheet(source, format="csv", separator=";", decimal=",",
                              numeric_columns=["mediana", "n"], source="example.csv")
    assert result["rows"][0][1]["decimal_value"] == "4.700000000000000001"
    assert result["rows"][0][2]["decimal_value"] == "0"
    assert result["rows"][1][1]["value"] is None
    assert result["rows"][1][1]["decimal_value"] is None
    assert result["rows"][1][1]["ref"]["coordinate"] == "B3"
    json.dumps(result)


def test_csv_bom_quoted_newline_and_original_row_number():
    result = read_spreadsheet(b'\xef\xbb\xbfdate,note\n\n2026,"a\nb"\n', format="csv")
    assert result["columns"] == ["date", "note"]
    assert result["rows"][0][1]["value"] == "a\nb"
    # Filas de registros CSV, no líneas físicas del archivo.
    assert result["rows"][0][1]["ref"]["row"] == 3


@pytest.mark.parametrize("content,kwargs", [
    (b"a,b\n1,2,3", {}),
    (b"a,b\n1", {}),
    (b"", {}),
    (b"a,a\n1,2", {"numeric_columns": ["a"]}),
    (b"a\nnot-a-number", {"numeric_columns": ["a"]}),
    (b"a\nNaN", {"numeric_columns": ["a"]}),
    (b"a\n1", {"numeric_columns": ["missing"]}),
    (b"a\n1", {"header_row": 0}),
])
def test_csv_rejects_invalid_data(content, kwargs):
    with pytest.raises(ReadError):
        read_spreadsheet(content, format="csv", **kwargs)


def test_csv_unicode_minus_and_encoding(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("valor\n−1.25\n", encoding="utf-8")
    result = read_spreadsheet(path, numeric_columns=["valor"])
    assert result["rows"][0][0]["value"] == "−1.25"
    assert result["rows"][0][0]["decimal_value"] == "-1.25"
    assert result["source"] == str(path.resolve())


def xlsx_fixture():
    """Libro mínimo de prueba: rango declarado incorrecto y fórmula sin caché."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>''')
        z.writestr("xl/workbook.xml", '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Datos" sheetId="1" r:id="rId1"/></sheets></workbook>''')
        z.writestr("xl/_rels/workbook.xml.rels", '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>''')
        z.writestr("xl/worksheets/sheet1.xml", '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>valor</t></is></c><c r="B1" t="inlineStr"><is><t>formula</t></is></c></row><row r="2"><c r="A2" t="n"><v>4.7</v></c><c r="B2"><f>A2*2</f></c></row><row r="4"><c r="A4" t="n"><v>0</v></c></row></sheetData></worksheet>''')
    return buffer.getvalue()


def test_xlsx_dimensions_formulas_padding_and_sheet():
    result = read_spreadsheet(xlsx_fixture(), format="xlsx", sheet="Datos")
    assert values(result["rows"][0]) == [4.7, "=A2*2"]
    assert values(result["rows"][1]) == [0, None]
    assert result["rows"][1][0]["ref"]["coordinate"] == "A4"
    with pytest.raises(ReadError):
        read_spreadsheet(xlsx_fixture(), format="xlsx", sheet="Missing")


def values(row):
    return [cell["value"] if cell else None for cell in row]


def test_html_selection_by_heading_not_position_and_spans():
    data = '''<h2>Otra tabla</h2><table><tr><td>ignorar</td></tr></table>
    <h2>Inflación</h2><table><tr><th rowspan="2">Medida</th><th colspan="2">2026</th></tr>
    <tr><th>Media</th><th>Mediana</th></tr><tr><td>12 meses</td><td>−1,20</td><td>0,00</td></tr></table>'''.encode()
    result = read_html(data, sections=["inflación"], source="source.html")
    table = result["tables"][0]
    assert table["index"] == 2
    assert values(table["rows"][1]) == ["Medida", "Media", "Mediana"]
    assert table["rows"][1][0]["ref"]["row"] == 1
    assert table["rows"][0][2]["ref"]["column"] == 2
    assert values(table["rows"][2]) == ["12 meses", "−1,20", "0,00"]


def test_html_caption_and_custom_title():
    data = b'<table><caption>Title</caption><tr><td class="name">Custom</td></tr></table>'
    assert read_html(data, sections=["Title"])["tables"][0]["section"] == "Title"
    assert read_html(data, title_selector=".name", sections=["Custom"])["tables"][0]["section"] == "Custom"


@pytest.mark.parametrize("data,kwargs", [
    (b"<p>No tables</p>", {}),
    (b"<table><tr><td>x</td></tr></table>", {"sections": ["missing"]}),
    (b'<table><tr><td rowspan="4">x</td></tr></table>', {}),
    (b'<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>', {}),
])
def test_html_invalid_or_missing_sections_fail(data, kwargs):
    with pytest.raises(ReadError):
        read_html(data, **kwargs)


def pdf_fixture():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    stream = b'BT /F1 12 Tf 30 250 Td (Example 4.70) Tj ET'
    objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    content, offsets = b'%PDF-1.4\n', [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content += str(n).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start = len(content)
    content += b'xref\n0 6\n0000000000 65535 f \n'
    content += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return content + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode()


def test_pdf_text_and_no_table_warning():
    result = read_pdf(pdf_fixture(), source="test.pdf")
    assert result["pages"][0]["text"] == "Example 4.70"
    assert result["pages"][0]["tables"] == []
    assert result["warnings"]


@pytest.mark.parametrize("pages", [[], [0], [2], [1, 1]])
def test_pdf_invalid_pages(pages):
    with pytest.raises(ReadError):
        read_pdf(pdf_fixture(), pages=pages)
