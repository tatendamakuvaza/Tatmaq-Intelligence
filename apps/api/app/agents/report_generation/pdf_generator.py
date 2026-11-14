"""The PDF report."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ...analytics.formatting import format_cell
from .charts import to_drawing
from .report_model import KIND_LABELS, ReportModel, evidence_line

# The app's palette: blue, with a violet accent beneath it, on faintly purple neutrals.
BRAND = colors.HexColor("#1D40B8")
BRAND_DARK = colors.HexColor("#17349F")
ACCENT = colors.HexColor("#8775E8")
ACCENT_LIGHT = colors.HexColor("#A698F1")
INK = colors.HexColor("#20284A")
MUTED = colors.HexColor("#5D6685")
RULE = colors.HexColor("#E6E3F4")
PANEL = colors.HexColor("#F4F2FD")
ZEBRA = colors.HexColor("#F9F8FE")

MARGIN = 18 * mm
CONTENT_WIDTH = A4[0] - 2 * MARGIN
NUMERIC = {"money", "percent", "integer", "number", "number4"}
KEEP_TOGETHER_ROWS = 18

STYLES = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=INK),
    "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10, leading=14, textColor=MUTED),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=BRAND_DARK,
                         spaceBefore=14, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=INK,
                         spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK,
                             leftIndent=12, bulletIndent=2, spaceAfter=4),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=10.5, textColor=MUTED),
    "note": ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=8, leading=10.5, textColor=MUTED,
                           spaceBefore=2, spaceAfter=6),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10, textColor=INK),
    "cell_right": ParagraphStyle("cell_right", fontName="Helvetica", fontSize=8, leading=10, textColor=INK,
                                 alignment=TA_RIGHT),
    "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white),
    "head_right": ParagraphStyle("head_right", fontName="Helvetica-Bold", fontSize=8, leading=10,
                                 textColor=colors.white, alignment=TA_RIGHT),
    "kpi_label": ParagraphStyle("kpi_label", fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED),
    "kpi_value": ParagraphStyle("kpi_value", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK),
    "meta_key": ParagraphStyle("meta_key", fontName="Helvetica-Bold", fontSize=8.5, leading=11.5, textColor=MUTED),
    "meta_value": ParagraphStyle("meta_value", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=INK),
}  # fmt: skip


def _text(value: Any) -> str:
    """Customer text made safe for ReportLab: markup escaped, unsupported characters replaced."""
    return escape(str(value).encode("cp1252", "replace").decode("cp1252"))


def _p(value: Any, style: str = "body") -> Paragraph:
    return Paragraph(_text(value), STYLES[style])


def _bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(_text(item), STYLES["bullet"], bulletText="\u2022") for item in items]


def _kpi_grid(kpis: list[dict[str, Any]], currency: str | None) -> Table:
    per_row = 4
    cells = []
    for kpi in kpis:
        note = f'<br/><font size="7" color="#5D6685">{_text(kpi["note"])}</font>' if kpi.get("note") else ""
        value = Paragraph(_text(format_cell(kpi["value"], kpi["format"], currency)) + note, STYLES["kpi_value"])
        cells.append([_p(kpi["label"].upper(), "kpi_label"), value])
    rows = [cells[i : i + per_row] for i in range(0, len(cells), per_row)]
    for row in rows:
        row += [""] * (per_row - len(row))
    grid = Table(rows, colWidths=[CONTENT_WIDTH / per_row] * per_row)
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, RULE),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))  # fmt: skip
    return grid


def _column_widths(columns: list[dict[str, str]], rows: list[dict[str, Any]], currency: str | None) -> list[float]:
    """Share the page width in proportion to how much text each column holds."""
    weights = []
    for column in columns:
        texts = [column["label"]] + [
            format_cell(row.get(column["key"]), column["format"], currency) for row in rows[:40]
        ]
        longest_word = max(len(word) for text in texts for word in (text.split() or [""]))
        # wide enough for the longest cell (up to a cap), and never so narrow that a word must break
        weights.append(max(min(max(len(text) for text in texts), 46), longest_word + 2, 6))
    total = sum(weights)
    return [CONTENT_WIDTH * weight / total for weight in weights]


def _data_table(table: dict[str, Any], currency: str | None) -> Table:
    columns, rows = table["columns"], table["rows"]
    header = [_p(c["label"], "head_right" if c["format"] in NUMERIC else "head") for c in columns]
    body = [
        [_p(format_cell(row.get(c["key"]), c["format"], currency), "cell_right" if c["format"] in NUMERIC else "cell")
         for c in columns]
        for row in rows
    ]  # fmt: skip
    flowable = Table([header, *body], colWidths=_column_widths(columns, rows, currency), repeatRows=1)
    flowable.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))  # fmt: skip
    return flowable


def _meta_table(model: ReportModel) -> Table:
    rows = [("Organisation", model.organisation), ("Dataset", model.dataset_label)]
    if model.period:
        rows.append(("Period covered", model.period))
    rows += [("Request", model.request), ("Prepared", model.generated_label)]
    table = Table([[_p(key, "meta_key"), _p(value, "meta_value")] for key, value in rows],
                  colWidths=[30 * mm, CONTENT_WIDTH - 30 * mm])  # fmt: skip
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))  # fmt: skip
    return table


def _page_furniture(model: ReportModel):
    def draw(canvas, document) -> None:
        canvas.saveState()
        width, height = A4
        if document.page == 1:
            canvas.setFillColor(BRAND_DARK)
            canvas.rect(0, height - 16 * mm, width, 16 * mm, stroke=0, fill=1)
            canvas.setFillColor(ACCENT)
            canvas.rect(0, height - 16.8 * mm, width, 0.8 * mm, stroke=0, fill=1)
            # logo mark: three rising bars
            x, y = MARGIN, height - 11.5 * mm
            canvas.setFillColor(colors.white)
            for i, bar in enumerate((3.0, 5.0, 7.0)):
                canvas.roundRect(x + i * 2.6 * mm, y, 1.8 * mm, bar * mm, 0.5 * mm, stroke=0, fill=1)
            canvas.setFillColor(ACCENT_LIGHT)
            canvas.circle(x + 9.6 * mm, y + 7.4 * mm, 0.9 * mm, stroke=0, fill=1)
            canvas.setFillColor(colors.white)
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawString(x + 13 * mm, height - 10.2 * mm, "TATMAQ Intelligence")
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 13 * mm, width - MARGIN, 13 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        footer = f"{model.title}  |  {model.organisation}  |  Analysis {model.job_id[:8]}"
        canvas.drawString(MARGIN, 9 * mm, footer.encode("cp1252", "replace").decode("cp1252"))
        canvas.drawRightString(width - MARGIN, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    return draw


def render_pdf(model: ReportModel, path: Path) -> None:
    document = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=24 * mm, bottomMargin=18 * mm,
        title=model.title, author="TATMAQ Intelligence", subject=model.objective,
    )  # fmt: skip
    story: list[Any] = [
        _p(model.title, "title"), Spacer(1, 2), _p(model.objective, "subtitle"), Spacer(1, 8), _meta_table(model),
        _p("Executive summary", "h2"), *_bullets(model.summary),
    ]  # fmt: skip

    for segment in model.segments:
        currency = segment.get("currency")
        heading = "Key figures" + (f": {segment['label']}" if model.multi_segment else "")
        if segment["kpis"]:
            story.append(KeepTogether([_p(heading, "h2"), _kpi_grid(segment["kpis"], currency)]))
        for chart in segment["charts"]:
            block = [_p(chart["title"], "h3"), to_drawing(chart, CONTENT_WIDTH)]
            if chart.get("note"):
                block.append(_p(chart["note"], "note"))
            story.append(KeepTogether(block))
        for table in segment["tables"]:
            title = table["title"] + (f" ({segment['label']})" if model.multi_segment else "")
            block = [_p(f"{title}  [{table['evidence_ref']}]", "h3"), _data_table(table, currency)]
            if table.get("note"):
                block.append(_p(table["note"], "note"))
            # short tables move to the next page whole rather than leaving a stray row behind
            story.extend([KeepTogether(block)] if len(table["rows"]) <= KEEP_TOGETHER_ROWS else block)

    story.append(_p("Findings", "h2"))
    story.append(_p("Each finding cites the evidence record it rests on; the records are listed at the end of "
                    "this report.", "small"))  # fmt: skip
    story.append(Spacer(1, 4))
    for finding in model.findings:
        label = KIND_LABELS.get(finding["kind"], "Finding")
        segment = f" ({model.segment_label(finding.get('segment'))})" if model.multi_segment else ""
        story.append(Paragraph(
            f'<b>{_text(finding["title"])}{_text(segment)}.</b> {_text(finding["statement"])} '
            f'<font size="7.5" color="#5D6685">[{_text(label)}, {_text(finding["evidence_ref"])}]</font>',
            STYLES["bullet"], bulletText="\u2022"))  # fmt: skip

    if model.next_steps:
        story += [_p("Suggested next steps", "h2"), *_bullets(model.next_steps)]
    if model.warnings:
        story += [_p("Data notes and limitations", "h2"), *_bullets(model.warnings)]
    if model.assumptions:
        story += [_p("Assumptions", "h2"), *_bullets(model.assumptions)]

    checks = model.verification.get("checks", [])
    if checks:
        passed = sum(1 for check in checks if check["passed"])
        story.append(_p("Verification", "h2"))
        story.append(_p(f"Before this report was written, the results were reconciled against an independent "
                        f"recalculation. {passed} of {len(checks)} checks passed.", "body"))  # fmt: skip
        story.append(Spacer(1, 4))
        story.append(_data_table({
            "columns": [{"key": "name", "label": "Check", "format": "text"},
                        {"key": "result", "label": "Result", "format": "text"},
                        {"key": "detail", "label": "Detail", "format": "text"}],
            "rows": [{"name": c["name"], "result": "Passed" if c["passed"] else "FAILED", "detail": c["detail"]}
                     for c in checks],
        }, None))  # fmt: skip

    story += [PageBreak(), _p("Evidence", "h2"),
              _p(f"All figures were computed by deterministic code from dataset '{model.dataset_name}' version "
                 f"{model.dataset_version} (SHA-256 {model.dataset_sha256}). No figure in this report was produced "
                 "by an AI model.", "small"), Spacer(1, 6)]  # fmt: skip
    for record in model.evidence:
        story.append(Paragraph(f'<b>{_text(record["ref"])}</b>  <font color="#5D6685">{_text(record["operation"])}</font>'
                               f'<br/>{_text(evidence_line(record))}', STYLES["small"]))  # fmt: skip
        story.append(Spacer(1, 5))
    story += [Spacer(1, 6), _p(model.narrative_source, "note")]

    furniture = _page_furniture(model)
    document.build(story, onFirstPage=furniture, onLaterPages=furniture)
