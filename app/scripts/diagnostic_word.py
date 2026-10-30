"""Small standard-library Word renderer for evidence-bound diagnostic drafts."""
from pathlib import Path
import struct
import zipfile
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def run(text):
    return '<w:r><w:t xml:space="preserve">' + escape(str(text)) + '</w:t></w:r>'


def paragraph(text, style=None, keep=False):
    props = ('<w:pPr>' + ('<w:pStyle w:val="' + style + '"/>' if style else '') +
             ('<w:keepNext/>' if keep else '') + '</w:pPr>') if style or keep else ''
    return '<w:p>' + props + run(text) + '</w:p>'


def figure(number, label, path):
    data = Path(path).read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError("figure must be PNG")
    width, height = struct.unpack('>II', data[16:24])
    cx = 5200000; cy = int(cx * height / width)
    if cy > 6300000:
        cx = int(cx * 6300000 / cy); cy = 6300000
    rid = 'image' + str(number)
    drawing = ('<w:p><w:pPr><w:keepLines/></w:pPr><w:r><w:drawing>'
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{number}" name="{escape(label)}"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:nvPicPr><pic:cNvPr id="{number}" name="{escape(label)}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rid}"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    return paragraph(f"Figure {number}. {label}", keep=True) + drawing


def table(title, rows):
    if not rows or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("table rows need a common width")
    n = len(rows[0]); width = 9000 // n
    border = ''.join(f'<w:{edge} w:val="single" w:color="D9D9D9" w:sz="4"/>'
                     for edge in ("top", "left", "bottom", "right", "insideH", "insideV"))
    body = []
    for index, row in enumerate(rows):
        cells = ''.join('<w:tc><w:tcPr><w:tcW w:w="' + str(width) + '" w:type="dxa"/>' +
                        ('<w:shd w:fill="E8EEF5"/>' if index == 0 else '') +
                        '</w:tcPr><w:p>' + ('<w:pPr><w:keepNext/></w:pPr>' if index == 0 else '') +
                        run(cell) + '</w:p></w:tc>' for cell in row)
        body.append('<w:tr><w:trPr><w:cantSplit/>' + ('<w:tblHeader/>' if index == 0 else '') +
                    '</w:trPr>' + cells + '</w:tr>')
    return (paragraph(title, keep=True) + '<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/>'
            '<w:tblBorders>' + border + '</w:tblBorders></w:tblPr><w:tblGrid>' +
            '<w:gridCol w:w="' + str(width) + '"/>' * n + '</w:tblGrid>' + ''.join(body) + '</w:tbl>')


def write(path, sections, figures):
    body = []
    for item in sections:
        body.append(paragraph(item["text"], item.get("style")))
        if item.get("table"):
            body.append(table(item["table"]["title"], item["table"]["rows"]))
        for number, label, image in item.get("figures", []):
            body.append(figure(number, label, image))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>' + ''.join(body) +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:bottom="1134" w:left="1134" w:right="1134"/></w:sectPr>'
        '</w:body></w:document>')
    styles = (f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/>'
        '</w:rPr></w:rPrDefault></w:docDefaults>' + ''.join(
            f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/>'
            f'<w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>'
            for name, size in (("Title", "32"), ("Heading1", "26"))) + '</w:styles>')
    relationships = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
        ''.join(f'<Relationship Id="image{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/figure{n}.png"/>' for n, _, _ in figures) +
        '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/_rels/document.xml.rels", relationships)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)
        for number, _, image in figures:
            archive.write(image, f"word/media/figure{number}.png")
