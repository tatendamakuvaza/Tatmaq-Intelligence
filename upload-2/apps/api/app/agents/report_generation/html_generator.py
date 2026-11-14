"""The HTML report: one self-contained file with inline styles and inline SVG charts.

It loads nothing from the network and contains no scripts, so it opens offline and is
safe to display inside the app. All customer text is escaped.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from ...analytics.formatting import format_cell
from .charts import to_svg
from .report_model import KIND_LABELS, ReportModel, evidence_line

NUMERIC = {"money", "percent", "integer", "number", "number4"}

CSS = """
*{box-sizing:border-box}body{margin:0;background:#F4F2FD;color:#20284A;font:15px/1.55 -apple-system,BlinkMacSystemFont,
"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.page{max-width:940px;margin:0 auto;background:#fff;min-height:100vh}
.band{background:linear-gradient(180deg,#17349F,#2150DA);color:#fff;padding:14px 40px;border-bottom:3px solid #8775E8;display:flex;align-items:center;
gap:10px;font-weight:700;letter-spacing:.01em}
.band svg{flex:none}main{padding:32px 40px 48px}
h1{font-size:28px;line-height:1.2;margin:0 0 4px}h2{font-size:18px;color:#17349F;margin:34px 0 10px;padding-top:6px;
border-top:1px solid #E6E3F4}h3{font-size:14px;margin:22px 0 8px}
.lead{color:#5D6685;margin:0 0 20px}.meta{display:grid;grid-template-columns:150px 1fr;gap:6px 16px;font-size:13.5px;
padding:14px 0;border-top:1px solid #E6E3F4;border-bottom:1px solid #E6E3F4}.meta dt{color:#5D6685;font-weight:600}
.meta dd{margin:0}ul{padding-left:20px;margin:8px 0}li{margin:6px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1px;background:#E6E3F4;
border:1px solid #E6E3F4;border-radius:6px;overflow:hidden}
.kpi{background:#F9F8FE;padding:12px 14px}.kpi .label{font-size:11px;letter-spacing:.06em;text-transform:uppercase;
color:#5D6685}.kpi .value{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:2px}
.kpi .note{font-size:11.5px;color:#5D6685}
.chart{border:1px solid #E6E3F4;border-radius:6px;padding:12px}.chart svg{display:block;width:100%;height:auto}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th{background:#1D40B8;color:#fff;text-align:left;padding:7px 10px;font-weight:600;white-space:nowrap}
td{padding:6px 10px;border-bottom:1px solid #E6E3F4;vertical-align:top}tr:nth-child(even) td{background:#F9F8FE}
.num{text-align:right;white-space:nowrap}.note{font-size:12.5px;color:#5D6685;font-style:italic;margin:6px 0 0}
.tag{font-size:11.5px;color:#5D6685;white-space:nowrap}.pass{color:#1D40B8;font-weight:600}.fail{color:#C5362C;
font-weight:700}.evidence{font-size:12.5px;color:#3C4466;margin:8px 0}.evidence b{color:#20284A}
footer{padding:18px 40px;border-top:1px solid #E6E3F4;color:#5D6685;font-size:12px}
@media(max-width:640px){main{padding:22px 18px 36px}.band,footer{padding-left:18px;padding-right:18px}
.meta{grid-template-columns:1fr}h1{font-size:23px}}
@media print{body{background:#fff}.page{max-width:none}h2{break-after:avoid}.chart,table{break-inside:avoid}}
"""

LOGO = ('<svg width="26" height="22" viewBox="0 0 26 22" aria-hidden="true"><rect x="0" y="13" width="5" height="9" '
        'rx="1.2" fill="#fff"/><rect x="7" y="7" width="5" height="15" rx="1.2" fill="#fff"/><rect x="14" y="1" '
        'width="5" height="21" rx="1.2" fill="#fff"/><circle cx="23" cy="3" r="2.6" fill="#C6BCF8"/></svg>')  # fmt: skip


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"


def _table(table: dict[str, Any], currency: str | None) -> str:
    head = "".join(
        f'<th class="{"num" if c["format"] in NUMERIC else ""}">{_e(c["label"])}</th>' for c in table["columns"]
    )
    body = "".join(
        "<tr>" + "".join(
            f'<td class="{"num" if c["format"] in NUMERIC else ""}">{_e(format_cell(row.get(c["key"]), c["format"], currency))}</td>'
            for c in table["columns"]
        ) + "</tr>"
        for row in table["rows"]
    )  # fmt: skip
    note = f'<p class="note">{_e(table["note"])}</p>' if table.get("note") else ""
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{note}'


def render_html(model: ReportModel, path: Path) -> None:
    out: list[str] = [
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(model.title)} - {_e(model.organisation)}</title><style>{CSS}</style></head><body>",
        f'<div class="page"><div class="band">{LOGO}<span>TATMAQ Intelligence</span></div><main>',
        f'<h1>{_e(model.title)}</h1><p class="lead">{_e(model.objective)}</p>',
        '<dl class="meta">',
        f"<dt>Organisation</dt><dd>{_e(model.organisation)}</dd><dt>Dataset</dt><dd>{_e(model.dataset_label)}</dd>",
    ]
    if model.period:
        out.append(f"<dt>Period covered</dt><dd>{_e(model.period)}</dd>")
    out.append(
        f"<dt>Request</dt><dd>{_e(model.request)}</dd><dt>Prepared</dt><dd>{_e(model.generated_label)}</dd></dl>"
    )
    out.append(f"<h2>Executive summary</h2>{_list(model.summary)}")

    for segment in model.segments:
        currency = segment.get("currency")
        suffix = f": {_e(segment['label'])}" if model.multi_segment else ""
        if segment["kpis"]:
            out.append(f'<h2>Key figures{suffix}</h2><div class="kpis">')
            for kpi in segment["kpis"]:
                note = f'<div class="note">{_e(kpi["note"])}</div>' if kpi.get("note") else ""
                out.append(f'<div class="kpi"><div class="label">{_e(kpi["label"])}</div><div class="value">'
                           f'{_e(format_cell(kpi["value"], kpi["format"], currency))}</div>{note}</div>')  # fmt: skip
            out.append("</div>")
        for chart in segment["charts"]:
            note = f'<p class="note">{_e(chart["note"])}</p>' if chart.get("note") else ""
            out.append(f'<h3>{_e(chart["title"])}{suffix}</h3><div class="chart">{to_svg(chart)}</div>{note}')
        for table in segment["tables"]:
            out.append(f'<h3>{_e(table["title"])}{suffix} <span class="tag">[{_e(table["evidence_ref"])}]</span></h3>')
            out.append(_table(table, currency))

    out.append("<h2>Findings</h2><ul>")
    for finding in model.findings:
        scope = f" ({_e(model.segment_label(finding.get('segment')))})" if model.multi_segment else ""
        out.append(f'<li><b>{_e(finding["title"])}{scope}.</b> {_e(finding["statement"])} '
                   f'<span class="tag">[{_e(KIND_LABELS.get(finding["kind"], "Finding"))}, {_e(finding["evidence_ref"])}]</span></li>')  # fmt: skip
    out.append("</ul>")
    if model.next_steps:
        out.append(f"<h2>Suggested next steps</h2>{_list(model.next_steps)}")
    if model.warnings:
        out.append(f"<h2>Data notes and limitations</h2>{_list(model.warnings)}")
    if model.assumptions:
        out.append(f"<h2>Assumptions</h2>{_list(model.assumptions)}")

    checks = model.verification.get("checks", [])
    if checks:
        passed = sum(1 for check in checks if check["passed"])
        out.append(f"<h2>Verification</h2><p>Before this report was written, the results were reconciled against an "
                   f"independent recalculation. {passed} of {len(checks)} checks passed.</p>"
                   '<div class="scroll"><table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>')  # fmt: skip
        for check in checks:
            result = '<span class="pass">Passed</span>' if check["passed"] else '<span class="fail">FAILED</span>'
            out.append(f"<tr><td>{_e(check['name'])}</td><td>{result}</td><td>{_e(check['detail'])}</td></tr>")
        out.append("</tbody></table></div>")

    out.append(f"<h2>Evidence</h2><p class=\"note\">All figures were computed by deterministic code from dataset "
               f"'{_e(model.dataset_name)}' version {model.dataset_version} (SHA-256 {_e(model.dataset_sha256)}). "
               "No figure in this report was produced by an AI model.</p>")  # fmt: skip
    for record in model.evidence:
        out.append(f'<p class="evidence"><b>{_e(record["ref"])}</b> <span class="tag">{_e(record["operation"])}</span><br>'
                   f"{_e(evidence_line(record))}</p>")  # fmt: skip
    out.append(
        f"</main><footer>{_e(model.narrative_source)} Analysis reference {_e(model.job_id)}.</footer></div></body></html>"
    )
    path.write_text("".join(out), encoding="utf-8")
