from __future__ import annotations

import re
import hashlib
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from corpus2node.scientific.schemas import (
    ScientificBBox,
    ScientificDocument,
    ScientificFormula,
    ScientificLocator,
    ScientificSection,
    ScientificSentence,
    ScientificTable,
    ScientificTableCell,
)

GROBID_COORDINATE_ELEMENTS = ("head", "p", "s", "title", "figure", "ref", "biblStruct", "formula")


class ScientificParseError(ValueError):
    pass


def parse_jats_xml(data: str | bytes, *, source_id: str) -> ScientificDocument:
    root = _xml_root(data)
    title = _text(_first(root, "article-title"))
    sections: list[ScientificSection] = []
    tables: list[ScientificTable] = []
    formulas: list[ScientificFormula] = []
    sentence_counter = 0

    def visit(section_element: ET.Element, parent_path: list[str]) -> None:
        nonlocal sentence_counter
        section_id = _id(section_element, "sec")
        heading = _text(_child(section_element, "title"))
        path = parent_path + ([heading] if heading else [])
        section = ScientificSection(section_id=section_id, title=heading, path=path)
        for paragraph in _children(section_element, "p"):
            citations = [_rid(value) for value in paragraph.iter() if _local(value.tag) == "xref" and value.get("ref-type") == "bibr"]
            explicit = [value for value in paragraph.iter() if _local(value.tag) == "s"]
            texts = [_text(value) for value in explicit] if explicit else _split_sentences(_text(paragraph))
            for text in filter(None, texts):
                sentence_counter += 1
                sentence_id = f"s{sentence_counter}"
                section.sentences.append(
                    ScientificSentence(
                        sentence_id=sentence_id,
                        text=text,
                        locator=ScientificLocator(
                            section_path=path,
                            sentence_id=sentence_id,
                            citation_ids=[value for value in citations if value],
                        ),
                    )
                )
        sections.append(section)
        for child in _children(section_element, "sec"):
            child_id = _id(child, "sec")
            section.child_section_ids.append(child_id)
            visit(child, path)

    body = _first(root, "body")
    if body is not None:
        for section in _children(body, "sec"):
            visit(section, [])
    for table_element in _all(root, "table-wrap"):
        table_id = _id(table_element, "table")
        locator = ScientificLocator(table_id=table_id)
        cells: list[ScientificTableCell] = []
        row_index = 0
        for row in [value for value in table_element.iter() if _local(value.tag) == "tr"]:
            column_index = 0
            for cell in [value for value in list(row) if _local(value.tag) in {"th", "td"}]:
                cell_locator = ScientificLocator(table_id=table_id, table_row=row_index, table_column=column_index)
                cells.append(
                    ScientificTableCell(
                        cell_id=cell.get("id") or f"{table_id}-r{row_index}c{column_index}",
                        text=_text(cell),
                        row=row_index,
                        column=column_index,
                        row_span=_positive_int(cell.get("rowspan")),
                        column_span=_positive_int(cell.get("colspan")),
                        locator=cell_locator,
                    )
                )
                column_index += _positive_int(cell.get("colspan"))
            row_index += 1
        tables.append(
            ScientificTable(
                table_id=table_id,
                label=_text(_first(table_element, "label")),
                caption=_text(_first(table_element, "caption")),
                cells=cells,
                locator=locator,
            )
        )
    for element in [value for value in root.iter() if _local(value.tag) in {"disp-formula", "inline-formula"}]:
        formula_id = _id(element, "formula")
        formulas.append(
            ScientificFormula(
                formula_id=formula_id,
                text=_text(element),
                locator=ScientificLocator(formula_id=formula_id),
            )
        )
    references = [_id(value, "ref") for value in _all(root, "ref")]
    return ScientificDocument(
        source_id=source_id,
        source_format="jats",
        title=title,
        sections=sections,
        tables=tables,
        formulas=formulas,
        reference_ids=references,
    )


def parse_tei_xml(data: str | bytes, *, source_id: str, from_grobid: bool = False) -> ScientificDocument:
    root = _xml_root(data)
    parent_by_child = {child: parent for parent in root.iter() for child in list(parent)}
    title = _text(_first(root, "title"))
    sections: list[ScientificSection] = []
    tables: list[ScientificTable] = []
    formulas: list[ScientificFormula] = []
    sentence_counter = 0

    def visit(div: ET.Element, parent_path: list[str]) -> None:
        nonlocal sentence_counter
        heading = _text(_child(div, "head"))
        path = parent_path + ([heading] if heading else [])
        section = ScientificSection(section_id=_id(div, "sec"), title=heading, path=path)
        for paragraph in _children(div, "p"):
            explicit = [value for value in paragraph.iter() if _local(value.tag) == "s"]
            sentence_elements = explicit or [paragraph]
            for sentence_element in sentence_elements:
                pieces = [_text(sentence_element)] if explicit else _split_sentences(_text(sentence_element))
                for text in filter(None, pieces):
                    sentence_counter += 1
                    sentence_id = _xml_id(sentence_element) or f"s{sentence_counter}"
                    bboxes = _coords(sentence_element.get("coords") or paragraph.get("coords", ""))
                    citations = [
                        _rid(value) for value in sentence_element.iter()
                        if _local(value.tag) == "ref" and value.get("type") in {"bibr", "biblio"}
                    ]
                    section.sentences.append(
                        ScientificSentence(
                            sentence_id=sentence_id,
                            text=text,
                            locator=ScientificLocator(
                                section_path=path,
                                sentence_id=sentence_id,
                                page=bboxes[0].page if bboxes else None,
                                bboxes=bboxes,
                                citation_ids=[value for value in citations if value],
                            ),
                        )
                    )
        sections.append(section)
        for child in _children(div, "div"):
            child_id = _id(child, "sec")
            section.child_section_ids.append(child_id)
            visit(child, path)

    body = _first(root, "body")
    if body is not None:
        for div in _children(body, "div"):
            visit(div, [])
    for table_element in _all(root, "table"):
        parent = parent_by_child.get(table_element)
        figure = parent if parent is not None and _local(parent.tag) == "figure" else None
        table_id = _id(figure if figure is not None else table_element, "table")
        table_boxes = _coords(
            table_element.get("coords", "") or (figure.get("coords", "") if figure is not None else "")
        )
        cells: list[ScientificTableCell] = []
        for row_index, row in enumerate(_children(table_element, "row")):
            column = 0
            for cell in _children(row, "cell"):
                boxes = _coords(cell.get("coords", "")) or table_boxes
                locator = ScientificLocator(
                    page=boxes[0].page if boxes else None,
                    bboxes=boxes,
                    table_id=table_id,
                    table_row=row_index,
                    table_column=column,
                )
                cells.append(
                    ScientificTableCell(
                        cell_id=_xml_id(cell) or f"{table_id}-r{row_index}c{column}",
                        text=_text(cell),
                        row=row_index,
                        column=column,
                        row_span=_positive_int(cell.get("rows")),
                        column_span=_positive_int(cell.get("cols")),
                        locator=locator,
                    )
                )
                column += _positive_int(cell.get("cols"))
        tables.append(
            ScientificTable(
                table_id=table_id,
                label=_text(_child(figure, "head")) if figure is not None else "",
                caption=_text(_child(figure, "figDesc")) if figure is not None else "",
                cells=cells,
                locator=ScientificLocator(
                    page=table_boxes[0].page if table_boxes else None,
                    bboxes=table_boxes,
                    table_id=table_id,
                ),
            )
        )
    for element in _all(root, "formula"):
        formula_id = _id(element, "formula")
        boxes = _coords(element.get("coords", ""))
        formulas.append(
            ScientificFormula(
                formula_id=formula_id,
                text=_text(element),
                locator=ScientificLocator(
                    page=boxes[0].page if boxes else None,
                    bboxes=boxes,
                    formula_id=formula_id,
                ),
            )
        )
    page_dimensions: dict[int, tuple[float, float]] = {}
    for surface in _all(root, "surface"):
        page = _surface_page(surface)
        if page:
            page_dimensions[page] = (float(surface.get("lrx", 0)), float(surface.get("lry", 0)))
    references = [_id(value, "ref") for value in _all(root, "biblStruct")]
    return ScientificDocument(
        source_id=source_id,
        source_format="grobid_tei" if from_grobid else "tei",
        title=title,
        sections=sections,
        tables=tables,
        formulas=formulas,
        reference_ids=references,
        page_dimensions=page_dimensions,
    )


def parse_grobid_pdf(
    pdf_path: str | Path,
    *,
    source_id: str,
    base_url: str = "http://localhost:8070",
    client: httpx.Client | None = None,
) -> ScientificDocument:
    content = request_grobid_tei(pdf_path, base_url=base_url, client=client)
    return parse_tei_xml(content, source_id=source_id, from_grobid=True)


def request_grobid_tei(
    pdf_path: str | Path,
    *,
    base_url: str = "http://localhost:8070",
    client: httpx.Client | None = None,
) -> bytes:
    path = Path(pdf_path)
    if not path.exists():
        raise ScientificParseError(f"PDF 不存在：{path}")
    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=3.0))
    try:
        with path.open("rb") as handle:
            response = client.post(
                f"{base_url.rstrip('/')}/api/processFulltextDocument",
                files={"input": (path.name, handle, "application/pdf")},
                data={
                    "segmentSentences": "1",
                    "includeRawCitations": "1",
                    "teiCoordinates": GROBID_COORDINATE_ELEMENTS,
                },
            )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ScientificParseError(f"GROBID 解析失败：{exc}") from exc
    finally:
        if owns_client:
            client.close()
    return response.content


def parse_scientific_xml(path: str | Path, *, source_id: str) -> ScientificDocument:
    data = Path(path).read_bytes()
    root = _xml_root(data)
    name = _local(root.tag).lower()
    if name == "article":
        return parse_jats_xml(data, source_id=source_id)
    if name == "tei":
        return parse_tei_xml(data, source_id=source_id)
    raise ScientificParseError(f"无法识别的科研 XML 根元素：{name}")


def _xml_root(data: str | bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ScientificParseError(f"XML 解析失败：{exc}") from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _all(element: ET.Element, name: str) -> list[ET.Element]:
    return [value for value in element.iter() if _local(value.tag) == name]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [value for value in list(element) if _local(value.tag) == name]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next(iter(_children(element, name)), None)


def _first(element: ET.Element, name: str) -> ET.Element | None:
    return next((value for value in element.iter() if _local(value.tag) == name), None)


def _text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _xml_id(element: ET.Element) -> str:
    return element.get("{http://www.w3.org/XML/1998/namespace}id", "") or element.get("id", "")


def _id(element: ET.Element, prefix: str) -> str:
    digest = hashlib.sha1(ET.tostring(element, encoding="utf-8")).hexdigest()[:12]
    return _xml_id(element) or f"{prefix}-{digest}"


def _rid(element: ET.Element) -> str:
    return (element.get("rid") or element.get("target") or "").lstrip("#")


def _positive_int(value: str | None) -> int:
    try:
        return max(1, int(value or 1))
    except ValueError:
        return 1


def _split_sentences(text: str) -> list[str]:
    return [value.strip() for value in re.split(r"(?<=[。！？])|(?<=[.!?])\s+", text) if value.strip()]


def _coords(value: str) -> list[ScientificBBox]:
    boxes: list[ScientificBBox] = []
    for raw in value.split(";"):
        fields = raw.strip().split(",")
        if len(fields) != 5:
            continue
        try:
            boxes.append(
                ScientificBBox(
                    page=int(fields[0]),
                    x=float(fields[1]),
                    y=float(fields[2]),
                    width=float(fields[3]),
                    height=float(fields[4]),
                )
            )
        except (ValueError, TypeError):
            continue
    return boxes


def _surface_page(surface: ET.Element) -> int | None:
    match = re.search(r"(\d+)$", _xml_id(surface) or surface.get("n", ""))
    return int(match.group(1)) if match else None
