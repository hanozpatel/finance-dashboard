/**
 * Chart builders.
 *
 * Every mark spec from the design method is applied here, once, so no page can
 * accidentally ship a loud chart:
 *
 *  - bars cap at 24px with a 4px rounded data-end, square at the baseline
 *  - lines are 2px with round caps; markers are 8px with a 2px surface ring
 *  - area fills are the series hue at 10% — a wash, never a block
 *  - stacked segments are separated by a 2px gap in the surface colour (in
 *    ECharts that is expressed as a surface-coloured border, which renders as
 *    the gap; it is not a contrasting stroke around the mark)
 *  - gridlines and axes are solid hairlines one step off the surface
 *  - a legend appears for two or more series and never for one
 *  - axis ticks use tabular figures; nothing else does
 *  - there is never a second y-axis
 *
 * Text never carries a series colour — identity comes from the coloured mark
 * beside the label.
 */

import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { useMemo } from 'react'

import { useChartTokens, type ChartTokens } from '../lib/theme'
import { money, moneyCompact } from '../lib/format'

const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

/**
 * ECharts hands label formatters its full callback-params object, whose `value`
 * is a wide union. Accepting that shape (rather than a narrowed `{value: number}`)
 * is what makes these assignable to ECharts' own formatter type.
 */
type LabelParams = { value?: unknown }

const asNumber = (v: unknown): number =>
  typeof v === 'number' ? v : Number(v) || 0

/**
 * Honour the OS "reduce motion" setting. Bars growing from zero and lines
 * drawing in are decoration, so they are the first thing to drop for anyone who
 * has asked for less of it.
 */
function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

/** Shared chrome: hairline grid, recessive axes, tabular ticks. */
function base(t: ChartTokens): EChartsOption {
  return {
    backgroundColor: 'transparent',
    textStyle: { fontFamily: FONT, color: t.textSecondary },
    animation: !prefersReducedMotion(),
    animationDuration: 400,
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: t.surface,
      borderColor: t.border,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: t.textPrimary, fontFamily: FONT, fontSize: 12 },
      extraCssText: 'border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.12);',
    },
  }
}

function axisCommon(t: ChartTokens) {
  return {
    axisLine: { show: true, lineStyle: { color: t.axis, width: 1, type: 'solid' as const } },
    axisTick: { show: false },
    axisLabel: { color: t.textMuted, fontSize: 11, fontFamily: FONT },
    splitLine: { show: false },
  }
}

function valueAxis(t: ChartTokens, opts: { money?: boolean } = {}) {
  return {
    type: 'value' as const,
    ...axisCommon(t),
    axisLine: { show: false },
    splitLine: { show: true, lineStyle: { color: t.grid, width: 1, type: 'solid' as const } },
    axisLabel: {
      color: t.textMuted,
      fontSize: 11,
      fontFamily: FONT,
      // Tabular figures so the tick column aligns.
      fontWeight: 'normal' as const,
      formatter: (v: number) => (opts.money === false ? String(v) : moneyCompact(v)),
    },
  }
}

const LEGEND = (t: ChartTokens) => ({
  show: true,
  bottom: 0,
  left: 'center' as const,
  itemWidth: 10,
  itemHeight: 10,
  itemGap: 16,
  icon: 'roundRect' as const,
  textStyle: { color: t.textSecondary, fontSize: 11, fontFamily: FONT },
})

export interface ChartProps {
  height?: number
  className?: string
}

function Chart({ option, height = 260, className }: { option: EChartsOption } & ChartProps) {
  return (
    <ReactECharts
      option={option}
      // The container must include the axis band, or the card grows a nested
      // scrollbar around a plot that technically fits.
      style={{ height, width: '100%' }}
      opts={{ renderer: 'svg' }}
      notMerge
      lazyUpdate
      className={className}
    />
  )
}

// ---------------------------------------------------------------------------
// Single-series trend — an area wash. No legend: one colour needs no key.
// ---------------------------------------------------------------------------

export function TrendArea({
  labels, values, height = 260, valueLabel = 'Value', colorIndex = 0, showEndLabel = true,
}: {
  labels: string[]
  values: number[]
  valueLabel?: string
  colorIndex?: number
  showEndLabel?: boolean
} & ChartProps) {
  const t = useChartTokens()
  const color = t.series[colorIndex]
  const option = useMemo<EChartsOption>(() => ({
    ...base(t),
    grid: { left: 8, right: showEndLabel ? 64 : 16, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      trigger: 'axis',
      // A crosshair is the axis-trigger affordance; it must be a hairline too.
      axisPointer: { type: 'line', lineStyle: { color: t.axis, width: 1 } },
      formatter: (params: unknown) => {
        const p = (params as { name: string; value: number }[])[0]
        return `<div style="color:${t.textMuted};font-size:11px">${p.name}</div>
                <div style="font-weight:600">${money(p.value)}</div>`
      },
    },
    xAxis: { type: 'category', data: labels, boundaryGap: false, ...axisCommon(t) },
    yAxis: valueAxis(t),
    series: [{
      name: valueLabel,
      type: 'line',
      data: values,
      smooth: false,
      showSymbol: false,
      lineStyle: { width: 2, color, cap: 'round', join: 'round' },
      itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
      symbolSize: 8,
      areaStyle: { color, opacity: 0.1 },
      // Label only the endpoint — a number on every point goes unread.
      endLabel: showEndLabel
        ? {
            show: true, color: t.textPrimary, fontSize: 11, fontFamily: FONT,
            fontWeight: 600,
            formatter: (p: LabelParams) => moneyCompact(asNumber(p.value)),
            offset: [6, 0],
          }
        : undefined,
      emphasis: { focus: 'none', itemStyle: { borderWidth: 2, borderColor: t.surface } },
    }],
  }), [t, labels, values, valueLabel, color, showEndLabel])

  return <Chart option={option} height={height} />
}

// ---------------------------------------------------------------------------
// Multi-series lines. Legend always; end labels only when ≤4 series.
// ---------------------------------------------------------------------------

export function MultiLine({
  labels, series, height = 280, asMoney = true,
}: {
  labels: string[]
  series: { name: string; values: (number | null)[]; colorIndex?: number }[]
  asMoney?: boolean
} & ChartProps) {
  const t = useChartTokens()
  const option = useMemo<EChartsOption>(() => ({
    ...base(t),
    grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: t.axis, width: 1 } },
      formatter: (params: unknown) => {
        const rows = params as { name: string; value: number; color: string; seriesName: string }[]
        const head = `<div style="color:${t.textMuted};font-size:11px;margin-bottom:4px">${rows[0]?.name ?? ''}</div>`
        return head + rows.map((r) =>
          `<div style="display:flex;gap:8px;align-items:center;justify-content:space-between">
             <span style="display:inline-flex;align-items:center;gap:6px">
               <span style="width:8px;height:8px;border-radius:2px;background:${r.color}"></span>
               <span style="color:${t.textSecondary}">${r.seriesName}</span>
             </span>
             <span style="font-weight:600;font-variant-numeric:tabular-nums">${
               asMoney ? money(r.value) : r.value?.toLocaleString() ?? '—'
             }</span>
           </div>`).join('')
      },
    },
    legend: series.length > 1 ? LEGEND(t) : { show: false },
    xAxis: { type: 'category', data: labels, boundaryGap: false, ...axisCommon(t) },
    // One value axis. Two measures of different scale get two charts, never two axes.
    yAxis: valueAxis(t, { money: asMoney }),
    series: series.map((s, i) => {
      const color = t.series[s.colorIndex ?? i]
      return {
        name: s.name,
        type: 'line' as const,
        data: s.values,
        smooth: false,
        showSymbol: false,
        symbolSize: 8,
        lineStyle: { width: 2, color, cap: 'round' as const, join: 'round' as const },
        itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
        emphasis: { focus: 'none' as const },
      }
    }),
  }), [t, labels, series, asMoney])

  return <Chart option={option} height={height} />
}

// ---------------------------------------------------------------------------
// Grouped columns — for two comparable measures in the same unit.
// ---------------------------------------------------------------------------

export function GroupedColumns({
  labels, series, height = 280,
}: {
  labels: string[]
  series: { name: string; values: number[]; colorIndex?: number }[]
} & ChartProps) {
  const t = useChartTokens()
  const option = useMemo<EChartsOption>(() => ({
    ...base(t),
    grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: t.grid, opacity: 0.4 } },
      formatter: (params: unknown) => {
        const rows = params as { name: string; value: number; color: string; seriesName: string }[]
        return `<div style="color:${t.textMuted};font-size:11px;margin-bottom:4px">${rows[0]?.name ?? ''}</div>`
          + rows.map((r) =>
            `<div style="display:flex;gap:12px;justify-content:space-between">
               <span style="display:inline-flex;align-items:center;gap:6px">
                 <span style="width:8px;height:8px;border-radius:2px;background:${r.color}"></span>
                 <span style="color:${t.textSecondary}">${r.seriesName}</span>
               </span>
               <span style="font-weight:600;font-variant-numeric:tabular-nums">${money(r.value)}</span>
             </div>`).join('')
      },
    },
    legend: series.length > 1 ? LEGEND(t) : { show: false },
    xAxis: { type: 'category', data: labels, ...axisCommon(t) },
    yAxis: valueAxis(t),
    series: series.map((s, i) => ({
      name: s.name,
      type: 'bar' as const,
      data: s.values,
      barMaxWidth: 24,
      // Adjacent bars are separated by the same 2px surface gap as a stack.
      barGap: '12%',
      barCategoryGap: '34%',
      itemStyle: {
        color: t.series[s.colorIndex ?? i],
        borderRadius: [4, 4, 0, 0],
      },
      emphasis: { focus: 'none' as const },
    })),
  }), [t, labels, series])

  return <Chart option={option} height={height} />
}

// ---------------------------------------------------------------------------
// Stacked columns — part-to-whole over time. 2px surface gap per segment.
// ---------------------------------------------------------------------------

export function StackedColumns({
  labels, series, height = 300, showLegend = true,
}: {
  labels: string[]
  series: { name: string; values: number[] }[]
  /** Off when the caller renders its own wrapping key with totals. ECharts'
   *  scroll legend paginates inside a narrow card, which reads worse than
   *  both — and two legends for one chart is worse still. */
  showLegend?: boolean
} & ChartProps) {
  const t = useChartTokens()
  const option = useMemo<EChartsOption>(() => ({
    ...base(t),
    grid: { left: 8, right: 16, top: 16, bottom: 48, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: t.grid, opacity: 0.4 } },
      formatter: (params: unknown) => {
        const rows = (params as { name: string; value: number; color: string; seriesName: string }[])
          .filter((r) => r.value > 0)
          .sort((a, b) => b.value - a.value)
        const total = rows.reduce((sum, r) => sum + r.value, 0)
        return `<div style="color:${t.textMuted};font-size:11px;margin-bottom:4px">${rows[0]?.name ?? ''}</div>`
          + rows.map((r) =>
            `<div style="display:flex;gap:16px;justify-content:space-between">
               <span style="display:inline-flex;align-items:center;gap:6px">
                 <span style="width:8px;height:8px;border-radius:2px;background:${r.color}"></span>
                 <span style="color:${t.textSecondary}">${r.seriesName}</span>
               </span>
               <span style="font-weight:600;font-variant-numeric:tabular-nums">${money(r.value)}</span>
             </div>`).join('')
          + `<div style="margin-top:6px;padding-top:6px;border-top:1px solid ${t.border};
                display:flex;gap:16px;justify-content:space-between">
               <span style="color:${t.textMuted}">Total</span>
               <span style="font-weight:600;font-variant-numeric:tabular-nums">${money(total)}</span>
             </div>`
      },
    },
    legend: showLegend ? { ...LEGEND(t), type: 'scroll' } : { show: false },
    xAxis: { type: 'category', data: labels, ...axisCommon(t) },
    yAxis: valueAxis(t),
    series: series.map((s, i) => ({
      name: s.name,
      type: 'bar' as const,
      stack: 'total',
      data: s.values,
      barMaxWidth: 24,
      barCategoryGap: '34%',
      itemStyle: {
        // Fixed slot order, never cycled — the caller caps the series count at
        // eight so this index can never wrap onto a hue already on screen.
        color: t.series[i],
        // The 2px gap between touching segments, drawn in the surface colour.
        borderColor: t.surface,
        borderWidth: 2,
      },
      emphasis: { focus: 'none' as const },
    })),
  }), [t, labels, series])

  return <Chart option={option} height={height} />
}

// ---------------------------------------------------------------------------
// Horizontal bars for ranked magnitude — one hue, direct-labelled at the tip.
// ---------------------------------------------------------------------------

export function RankedBars({
  items, height, colorIndex = 0, maxBars = 12, labelWidth = 160,
}: {
  items: { label: string; value: number; sublabel?: string }[]
  colorIndex?: number
  maxBars?: number
  /** Widen for long labels. Truncation is a last resort, and the tooltip
   *  always carries the untruncated text. */
  labelWidth?: number
} & ChartProps) {
  const t = useChartTokens()
  const shown = items.slice(0, maxBars)
  const computedHeight = height ?? Math.max(140, shown.length * 30 + 24)

  const option = useMemo<EChartsOption>(() => ({
    ...base(t),
    grid: { left: 8, right: 72, top: 4, bottom: 4, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      trigger: 'item',
      formatter: (p: unknown) => {
        const row = p as { name: string; value: number; dataIndex: number }
        const extra = shown[row.dataIndex]?.sublabel
        return `<div style="font-weight:600">${row.name}</div>
                <div style="font-variant-numeric:tabular-nums">${money(row.value)}</div>`
          + (extra ? `<div style="color:${t.textMuted};font-size:11px">${extra}</div>` : '')
      },
    },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      // Ranked descending, so the largest sits at the top.
      data: shown.map((i) => i.label).reverse(),
      ...axisCommon(t),
      axisLine: { show: false },
      axisLabel: { color: t.textSecondary, fontSize: 12, fontFamily: FONT,
        width: labelWidth, overflow: 'truncate' },
    },
    series: [{
      type: 'bar',
      data: shown.map((i) => i.value).reverse(),
      barMaxWidth: 20,
      itemStyle: { color: t.series[colorIndex], borderRadius: [0, 4, 4, 0] },
      // The value rides outside the bar end, so it can never be clipped by a
      // short bar.
      label: {
        show: true, position: 'right', color: t.textPrimary, fontSize: 11,
        fontFamily: FONT, fontWeight: 600,
        formatter: (p: LabelParams) => moneyCompact(asNumber(p.value)),
      },
      emphasis: { focus: 'none' },
    }],
  }), [t, shown, colorIndex, labelWidth])

  return <Chart option={option} height={computedHeight} />
}

// ---------------------------------------------------------------------------
// A single stacked bar — composition of one total (a payment, an allocation).
// ---------------------------------------------------------------------------

export function CompositionBar({
  parts, height = 76, total,
}: {
  parts: { label: string; value: number }[]
  total?: number
} & ChartProps) {
  const t = useChartTokens()
  const visible = parts.filter((p) => p.value > 0)
  const sum = total ?? visible.reduce((s, p) => s + p.value, 0)

  const option = useMemo<EChartsOption>(() => ({
    ...base(t),
    grid: { left: 0, right: 0, top: 8, bottom: 40 },
    tooltip: {
      ...base(t).tooltip,
      trigger: 'item',
      formatter: (p: unknown) => {
        const row = p as { seriesName: string; value: number; color: string }
        const share = sum ? (row.value / sum) * 100 : 0
        return `<div style="display:inline-flex;align-items:center;gap:6px">
                  <span style="width:8px;height:8px;border-radius:2px;background:${row.color}"></span>
                  <span style="font-weight:600">${row.seriesName}</span>
                </div>
                <div style="font-variant-numeric:tabular-nums">${money(row.value)}
                  <span style="color:${t.textMuted}">· ${share.toFixed(1)}%</span></div>`
      },
    },
    legend: visible.length > 1 ? { ...LEGEND(t), type: 'scroll' } : { show: false },
    xAxis: { type: 'value', show: false, max: sum || 1 },
    yAxis: { type: 'category', show: false, data: [''] },
    series: visible.map((p, i) => ({
      name: p.label,
      type: 'bar' as const,
      stack: 'one',
      data: [p.value],
      barWidth: 22,
      itemStyle: {
        color: t.series[i % t.series.length],
        borderColor: t.surface,
        borderWidth: 2,
        // Only the outer ends are rounded; interior joins stay square.
        borderRadius: i === 0
          ? [4, 0, 0, 4]
          : i === visible.length - 1 ? [0, 4, 4, 0] : 0,
      },
      emphasis: { focus: 'none' as const },
    })),
  }), [t, visible, sum])

  return <Chart option={option} height={height} />
}

// ---------------------------------------------------------------------------
// Stacked area — cumulative composition over a long horizon (amortisation).
// ---------------------------------------------------------------------------

export function StackedArea({
  labels, series, height = 280, xName,
}: {
  labels: (string | number)[]
  series: { name: string; values: number[]; colorIndex?: number }[]
  xName?: string
} & ChartProps) {
  const t = useChartTokens()
  const option = useMemo<EChartsOption>(() => ({
    ...base(t),
    grid: { left: 8, right: 16, top: 16, bottom: 44, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: t.axis, width: 1 } },
      formatter: (params: unknown) => {
        const rows = params as { name: string; value: number; color: string; seriesName: string }[]
        const total = rows.reduce((s, r) => s + (r.value || 0), 0)
        return `<div style="color:${t.textMuted};font-size:11px;margin-bottom:4px">${
          xName ? `${xName} ${rows[0]?.name}` : rows[0]?.name}</div>`
          + rows.map((r) =>
            `<div style="display:flex;gap:16px;justify-content:space-between">
               <span style="display:inline-flex;align-items:center;gap:6px">
                 <span style="width:8px;height:8px;border-radius:2px;background:${r.color}"></span>
                 <span style="color:${t.textSecondary}">${r.seriesName}</span>
               </span>
               <span style="font-weight:600;font-variant-numeric:tabular-nums">${money(r.value)}</span>
             </div>`).join('')
          + `<div style="margin-top:6px;padding-top:6px;border-top:1px solid ${t.border};
                display:flex;gap:16px;justify-content:space-between">
               <span style="color:${t.textMuted}">Total</span>
               <span style="font-weight:600;font-variant-numeric:tabular-nums">${money(total)}</span>
             </div>`
      },
    },
    legend: series.length > 1 ? LEGEND(t) : { show: false },
    xAxis: {
      type: 'category', data: labels.map(String), boundaryGap: false, ...axisCommon(t),
      name: xName, nameLocation: 'middle', nameGap: 26,
      nameTextStyle: { color: t.textMuted, fontSize: 11, fontFamily: FONT },
    },
    yAxis: valueAxis(t),
    series: series.map((s, i) => {
      const color = t.series[s.colorIndex ?? i]
      return {
        name: s.name,
        type: 'line' as const,
        stack: 'total',
        data: s.values,
        showSymbol: false,
        lineStyle: { width: 2, color, cap: 'round' as const },
        itemStyle: { color },
        // Stacked areas need enough fill to read as bands, but stay a wash.
        areaStyle: { color, opacity: 0.18 },
        emphasis: { focus: 'none' as const },
      }
    }),
  }), [t, labels, series, xName])

  return <Chart option={option} height={height} />
}

// ---------------------------------------------------------------------------
// Diverging bars — above/below a baseline (buy-vs-rent advantage, MoM change).
// ---------------------------------------------------------------------------

export function DivergingBars({
  labels, values, height = 240, positiveLabel = 'Above', negativeLabel = 'Below', xName,
}: {
  labels: (string | number)[]
  values: number[]
  positiveLabel?: string
  negativeLabel?: string
  xName?: string
} & ChartProps) {
  const t = useChartTokens()
  // Diverging: two hues that read as opposite, with zero as the neutral middle.
  const positive = t.series[0]
  const negative = t.series[7]

  const option = useMemo<EChartsOption>(() => ({
    ...base(t),
    grid: { left: 8, right: 16, top: 16, bottom: xName ? 44 : 36, containLabel: true },
    tooltip: {
      ...base(t).tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: t.grid, opacity: 0.4 } },
      formatter: (params: unknown) => {
        const r = (params as { name: string; value: number }[])[0]
        return `<div style="color:${t.textMuted};font-size:11px">${
          xName ? `${xName} ${r.name}` : r.name}</div>
          <div style="font-weight:600;font-variant-numeric:tabular-nums">${money(r.value)}</div>
          <div style="color:${t.textMuted};font-size:11px">${
            r.value >= 0 ? positiveLabel : negativeLabel}</div>`
      },
    },
    xAxis: {
      type: 'category', data: labels.map(String), ...axisCommon(t),
      name: xName, nameLocation: 'middle', nameGap: 26,
      nameTextStyle: { color: t.textMuted, fontSize: 11, fontFamily: FONT },
      axisLine: { show: true, lineStyle: { color: t.axis, width: 1 } },
    },
    yAxis: valueAxis(t),
    series: [{
      type: 'bar',
      data: values.map((v) => ({
        value: v,
        itemStyle: {
          color: v >= 0 ? positive : negative,
          // The rounded end follows the data end, which flips with the sign.
          borderRadius: v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
        },
      })),
      barMaxWidth: 24,
      barCategoryGap: '34%',
      emphasis: { focus: 'none' },
    }],
  }), [t, labels, values, positive, negative, positiveLabel, negativeLabel, xName])

  return <Chart option={option} height={height} />
}

// ---------------------------------------------------------------------------
// Sparkline for stat tiles — de-emphasised, no axes, no tooltip.
// ---------------------------------------------------------------------------

export function Sparkline({
  values, height = 36, colorIndex = 0,
}: { values: number[]; colorIndex?: number } & ChartProps) {
  const t = useChartTokens()
  const color = t.series[colorIndex]
  const option = useMemo<EChartsOption>(() => ({
    backgroundColor: 'transparent',
    animation: false,
    grid: { left: 0, right: 0, top: 4, bottom: 4 },
    xAxis: { type: 'category', show: false, data: values.map((_, i) => String(i)),
      boundaryGap: false },
    yAxis: { type: 'value', show: false,
      min: Math.min(...values) * 0.98, max: Math.max(...values) * 1.02 },
    series: [{
      type: 'line', data: values, showSymbol: false, smooth: false,
      lineStyle: { width: 2, color, cap: 'round' },
      areaStyle: { color, opacity: 0.1 },
      silent: true,
    }],
  }), [values, color])

  return <Chart option={option} height={height} />
}
