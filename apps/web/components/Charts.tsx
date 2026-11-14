"use client";

import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { compact, formatValue } from "@/lib/format";
import type { Chart } from "@/types/api";

// Blue first, then the violet that sits beneath it; the last two only appear when a chart
// has three or four series, and are chosen to stay distinct from both.
const PALETTE = ["#2553E0", "#8775E8", "#22A3C7", "#E0892B"];
const NEGATIVE = "#D9453B";
const AXIS = { fontSize: 12, fill: "#5D6685" };
const GRID = "#E6E3F4";
const CURSOR = { fill: "#F1EEFC" };
const TOOLTIP = { borderRadius: 10, border: "1px solid #E6E3F4", boxShadow: "0 10px 28px rgba(62, 58, 150, 0.14)", fontSize: 13 };

function shortCategory(label: string): string {
  const match = /^([A-Z][a-z]{2}) \d{2}(\d{2})$/.exec(label);
  return match ? `${match[1]} '${match[2]}` : label;
}

export function ChartView({ chart, currency }: { chart: Chart; currency: string | null }) {
  const data = chart.categories.map((category, index) => {
    const row: Record<string, string | number | null> = { category };
    chart.series.forEach((series) => (row[series.name] = series.values[index] ?? null));
    return row;
  });
  const formats = Object.fromEntries(chart.series.map((series) => [series.name, series.format]));
  const tooltip = (value: unknown, name: unknown) =>
    [formatValue(value as number, formats[String(name)] ?? "number", currency), String(name)] as [string, string];

  if (chart.orientation === "horizontal") {
    const series = chart.series[0];
    const width = Math.min(190, Math.max(...chart.categories.map((category) => category.length)) * 7 + 12);
    return (
      <div style={{ height: 44 + chart.categories.length * 34 }} role="img" aria-label={chart.title}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 0 }}>
            <CartesianGrid horizontal={false} stroke={GRID} />
            <XAxis type="number" tick={AXIS} tickFormatter={(value: number) => compact(value, series.format)} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="category" tick={AXIS} width={width} axisLine={false} tickLine={false} interval={0} />
            <Tooltip formatter={tooltip} cursor={CURSOR} contentStyle={TOOLTIP} />
            <Bar dataKey={series.name} radius={[0, 5, 5, 0]} maxBarSize={22}>
              {data.map((row, index) => (
                <Cell key={index} fill={Number(row[series.name]) < 0 ? NEGATIVE : PALETTE[0]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  const left = chart.series.filter((series) => series.axis !== "right");
  const right = chart.series.filter((series) => series.axis === "right");
  return (
    <div className="chart-box" role="img" aria-label={chart.title}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: right.length ? 0 : 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="category" tick={AXIS} tickFormatter={shortCategory} axisLine={{ stroke: "#CFCBE6" }} tickLine={false} minTickGap={8} />
          <YAxis yAxisId="left" tick={AXIS} width={48} tickFormatter={(value: number) => compact(value, left[0]?.format ?? "number")} axisLine={false} tickLine={false} />
          {right.length ? (
            <YAxis yAxisId="right" orientation="right" tick={AXIS} width={44} tickFormatter={(value: number) => compact(value, right[0].format)} axisLine={false} tickLine={false} />
          ) : null}
          <Tooltip formatter={tooltip} cursor={CURSOR} contentStyle={TOOLTIP} />
          {chart.series.length > 1 ? <Legend wrapperStyle={{ fontSize: 13 }} /> : null}
          {chart.series.map((series, index) =>
            series.type === "line" ? (
              <Line key={series.name} yAxisId={series.axis === "right" ? "right" : "left"} type="monotone" dataKey={series.name} stroke={PALETTE[index % PALETTE.length]} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} />
            ) : (
              <Bar key={series.name} yAxisId="left" dataKey={series.name} fill={PALETTE[index % PALETTE.length]} radius={[5, 5, 0, 0]} maxBarSize={46}>
                {data.map((row, cell) => (
                  <Cell key={cell} fill={Number(row[series.name]) < 0 ? NEGATIVE : PALETTE[index % PALETTE.length]} />
                ))}
              </Bar>
            ),
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
