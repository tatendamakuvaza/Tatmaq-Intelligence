"""Charts drawn from one layout, for two outputs.

``layout`` turns a chart description into plain shapes (rectangles, lines, text) with
coordinates. ``to_svg`` writes those shapes as inline SVG for the HTML report and
``to_drawing`` builds the same shapes as vector graphics for the PDF. One layout means
the two reports show the identical chart, and there is no image library to install.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from html import escape
from typing import Any

# The app's palette: blue first, then the violet that sits beneath it. The last two colours
# appear only when a chart has three or four series. Keep in step with the web app's Charts.tsx.
PALETTE = ("#2553E0", "#8775E8", "#22A3C7", "#E0892B")
NEGATIVE = "#D9453B"
GRID, AXIS, TEXT = "#E6E3F4", "#9AA0BC", "#3C4466"
FONT = "Helvetica"
_MONTH_LABEL = re.compile(r"^([A-Z][a-z]{2}) \d{2}(\d{2})$")


@dataclass(frozen=True)
class Shape:
    kind: str  # rect | line | polyline | circle | text
    points: tuple[float, ...]
    fill: str | None = None
    stroke: str | None = None
    width: float = 1.0
    text: str = ""
    size: float = 7.5
    anchor: str = "start"


def nice_ticks(low: float, high: float, target: int = 5) -> list[float]:
    """Round axis values (multiples of 1, 2, 2.5 or 5) spanning ``low`` to ``high``."""
    if high <= low:
        high = low + 1.0
    raw = (high - low) / target
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw * 0.999) * magnitude
    first, last = math.floor(low / step + 1e-9) * step, math.ceil(high / step - 1e-9) * step
    return [round(first + i * step, 10) for i in range(round((last - first) / step) + 1)]


def axis_label(value: float, kind: str) -> str:
    if kind == "percent":
        return f"{value:g}%"
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:g}M"
    if magnitude >= 1_000:
        return f"{value / 1_000:g}k"
    return f"{value:g}"


def value_label(value: float, kind: str) -> str:
    if kind == "percent":
        return f"{value:.1f}%"
    return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:,.2f}"


def short_category(label: str) -> str:
    """``Nov 2025`` -> ``Nov '25`` so twelve months fit along an axis."""
    match = _MONTH_LABEL.match(label)
    return f"{match[1]} '{match[2]}" if match else label


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "\u2026"


def chart_height(chart: dict[str, Any]) -> float:
    if chart.get("orientation") == "horizontal":
        return 30 + 24 * len(chart["categories"])
    return 190


def layout(chart: dict[str, Any], width: float, height: float) -> list[Shape]:
    if not chart["categories"] or not chart["series"]:
        return []
    return (
        _horizontal(chart, width, height)
        if chart.get("orientation") == "horizontal"
        else _vertical(chart, width, height)
    )


def _vertical(chart: dict[str, Any], width: float, height: float) -> list[Shape]:
    categories, series = chart["categories"], chart["series"]
    left = [s for s in series if s.get("axis") != "right"]
    right = [s for s in series if s.get("axis") == "right"]
    legend = 16 if len(series) > 1 else 0
    margin_left, margin_right, margin_top, margin_bottom = 42, (38 if right else 10), 8 + legend, 26
    plot_w, plot_h = width - margin_left - margin_right, height - margin_top - margin_bottom
    shapes: list[Shape] = []

    def scale(group: list[dict[str, Any]]) -> tuple[list[float], Any]:
        values = [v for s in group for v in s["values"] if v is not None] or [0.0]
        ticks = nice_ticks(min(0.0, min(values)), max(0.0, max(values)))
        low, high = ticks[0], ticks[-1]
        return ticks, lambda v: margin_top + plot_h * (1 - (v - low) / (high - low))

    ticks, y = scale(left or right)
    left_kind = (left or right)[0].get("format", "number")
    for tick in ticks:
        shapes.append(Shape("line", (margin_left, y(tick), margin_left + plot_w, y(tick)), stroke=GRID, width=0.6))
        shapes.append(
            Shape("text", (margin_left - 5, y(tick) + 2.5), text=axis_label(tick, left_kind), fill=TEXT, anchor="end")
        )

    band = plot_w / len(categories)
    centre = lambda i: margin_left + i * band + band / 2  # noqa: E731
    bars = [s for s in left if s.get("type", "bar") == "bar"]
    for index, item in enumerate(bars):
        bar_w = band * 0.62 / len(bars)
        for i, value in enumerate(item["values"]):
            if value is None:
                continue
            x = margin_left + i * band + band * 0.19 + index * bar_w
            top, bottom = sorted((y(value), y(0.0)))
            shapes.append(Shape("rect", (x, top, bar_w, max(bottom - top, 0.6)),
                                fill=PALETTE[index % len(PALETTE)] if value >= 0 else NEGATIVE))  # fmt: skip
    shapes.append(Shape("line", (margin_left, y(0.0), margin_left + plot_w, y(0.0)), stroke=AXIS, width=0.8))

    def draw_line(item: dict[str, Any], to_y: Any, colour: str) -> None:
        run: list[float] = []
        for i, value in enumerate(item["values"]):
            if value is None:
                if len(run) >= 4:
                    shapes.append(Shape("polyline", tuple(run), stroke=colour, width=1.6))
                run = []
                continue
            run += [centre(i), to_y(value)]
            shapes.append(Shape("circle", (centre(i), to_y(value), 2.2), fill=colour))
        if len(run) >= 4:
            shapes.append(Shape("polyline", tuple(run), stroke=colour, width=1.6))

    colour_of = {id(s): PALETTE[i % len(PALETTE)] for i, s in enumerate(series)}
    for item in (s for s in left if s.get("type") == "line"):
        draw_line(item, y, colour_of[id(item)])
    if right and left:
        right_ticks, right_y = scale(right)
        for tick in right_ticks:
            shapes.append(Shape("text", (margin_left + plot_w + 5, right_y(tick) + 2.5),
                                text=axis_label(tick, right[0].get("format", "number")), fill=TEXT))  # fmt: skip
        for item in right:
            draw_line(item, right_y, colour_of[id(item)])
    elif right:
        for item in right:
            draw_line(item, y, colour_of[id(item)])

    every = math.ceil(len(categories) / 14)
    for i, label in enumerate(categories):
        if i % every == 0:
            shapes.append(Shape("text", (centre(i), margin_top + plot_h + 11), text=_truncate(short_category(label), 12),
                                fill=TEXT, anchor="middle"))  # fmt: skip
    if legend:
        x = margin_left
        for item in series:
            shapes.append(Shape("rect", (x, 2, 8, 8), fill=colour_of[id(item)]))
            shapes.append(Shape("text", (x + 12, 9), text=item["name"], fill=TEXT, size=8))
            x += 22 + len(item["name"]) * 4.4
    return shapes


def _horizontal(chart: dict[str, Any], width: float, height: float) -> list[Shape]:
    categories, item = chart["categories"], chart["series"][0]
    values = [0.0 if v is None else v for v in item["values"]]
    kind = item.get("format", "number")
    margin_left = min(150.0, max(len(c) for c in categories) * 4.5 + 10)
    margin_right, margin_top, margin_bottom = 50, 4, 16
    plot_w, plot_h = width - margin_left - margin_right, height - margin_top - margin_bottom
    ticks = nice_ticks(min(0.0, min(values)), max(0.0, max(values)), 4)
    low, high = ticks[0], ticks[-1]
    x = lambda v: margin_left + plot_w * (v - low) / (high - low)  # noqa: E731
    shapes: list[Shape] = []
    for tick in ticks:
        shapes.append(Shape("line", (x(tick), margin_top, x(tick), margin_top + plot_h), stroke=GRID, width=0.6))
        shapes.append(
            Shape("text", (x(tick), margin_top + plot_h + 11), text=axis_label(tick, kind), fill=TEXT, anchor="middle")
        )
    row = plot_h / len(categories)
    bar_h = row * 0.62
    for i, (label, value) in enumerate(zip(categories, values, strict=True)):
        top = margin_top + i * row + (row - bar_h) / 2
        start, end = sorted((x(0.0), x(value)))
        shapes.append(
            Shape("rect", (start, top, max(end - start, 0.6), bar_h), fill=PALETTE[0] if value >= 0 else NEGATIVE)
        )
        shapes.append(Shape("text", (margin_left - 6, top + bar_h / 2 + 2.6), text=_truncate(label, 30), fill=TEXT,
                            anchor="end", size=8))  # fmt: skip
        shapes.append(Shape("text", (end + 4, top + bar_h / 2 + 2.6), text=value_label(value, kind), fill=TEXT))
    shapes.append(Shape("line", (x(0.0), margin_top, x(0.0), margin_top + plot_h), stroke=AXIS, width=0.8))
    return shapes


def to_svg(chart: dict[str, Any], width: float = 640) -> str:
    height = chart_height(chart)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" role="img" '
             f'aria-label="{escape(chart["title"], quote=True)}" font-family="Helvetica, Arial, sans-serif">']  # fmt: skip
    for shape in layout(chart, width, height):
        p = shape.points
        if shape.kind == "rect":
            parts.append(
                f'<rect x="{p[0]:.1f}" y="{p[1]:.1f}" width="{p[2]:.1f}" height="{p[3]:.1f}" fill="{shape.fill}" rx="1.5"/>'
            )
        elif shape.kind == "line":
            parts.append(f'<line x1="{p[0]:.1f}" y1="{p[1]:.1f}" x2="{p[2]:.1f}" y2="{p[3]:.1f}" stroke="{shape.stroke}" '
                         f'stroke-width="{shape.width:g}"/>')  # fmt: skip
        elif shape.kind == "polyline":
            points = " ".join(f"{p[i]:.1f},{p[i + 1]:.1f}" for i in range(0, len(p), 2))
            parts.append(f'<polyline points="{points}" fill="none" stroke="{shape.stroke}" stroke-width="{shape.width:g}" '
                         'stroke-linejoin="round"/>')  # fmt: skip
        elif shape.kind == "circle":
            parts.append(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="{p[2]:g}" fill="{shape.fill}"/>')
        elif shape.kind == "text":
            parts.append(f'<text x="{p[0]:.1f}" y="{p[1]:.1f}" font-size="{shape.size:g}" fill="{shape.fill}" '
                         f'text-anchor="{shape.anchor}">{escape(shape.text)}</text>')  # fmt: skip
    parts.append("</svg>")
    return "".join(parts)


def to_drawing(chart: dict[str, Any], width: float) -> Any:
    """The chart as a ReportLab drawing (vector graphics) for the PDF."""
    from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
    from reportlab.lib.colors import HexColor

    height = chart_height(chart)
    drawing = Drawing(width, height)
    flip = lambda value: height - value  # noqa: E731  (PDF coordinates start at the bottom)
    for shape in layout(chart, width, height):
        p = shape.points
        if shape.kind == "rect":
            drawing.add(Rect(p[0], flip(p[1] + p[3]), p[2], p[3], fillColor=HexColor(shape.fill), strokeColor=None))
        elif shape.kind == "line":
            drawing.add(
                Line(p[0], flip(p[1]), p[2], flip(p[3]), strokeColor=HexColor(shape.stroke), strokeWidth=shape.width)
            )
        elif shape.kind == "polyline":
            points = [flip(v) if i % 2 else v for i, v in enumerate(p)]
            drawing.add(PolyLine(points, strokeColor=HexColor(shape.stroke), strokeWidth=shape.width))
        elif shape.kind == "circle":
            drawing.add(Circle(p[0], flip(p[1]), p[2], fillColor=HexColor(shape.fill), strokeColor=None))
        elif shape.kind == "text":
            safe = shape.text.encode("cp1252", "replace").decode("cp1252")
            drawing.add(String(p[0], flip(p[1]), safe, fontName=FONT, fontSize=shape.size,
                               fillColor=HexColor(shape.fill), textAnchor=shape.anchor))  # fmt: skip
    return drawing
