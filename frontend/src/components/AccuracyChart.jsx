/**
 * AccuracyChart — Recharts line chart of accuracy vs. forecast-hour offset.
 *
 * Shows how each parameter degrades as the forecast ages.
 * X-axis: integer hour bucket into TAF valid period (0 = first hour, 23 = last).
 * Y-axis: accuracy score 0–100%.
 */

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts'

const LINES = [
  { key: 'overall_score',          label: 'Overall',      color: '#6366f1', width: 2.5 },
  { key: 'ceiling_coverage_score', label: 'Sky Coverage', color: '#0ea5e9', width: 1.5 },
  { key: 'ceiling_altitude_score', label: 'Ceiling Alt',  color: '#38bdf8', width: 1.5 },
  { key: 'visibility_score',       label: 'Visibility',   color: '#f59e0b', width: 1.5 },
  { key: 'wind_speed_score',       label: 'Wind Speed',   color: '#10b981', width: 1.5 },
  { key: 'wind_dir_score',         label: 'Wind Dir',     color: '#f43f5e', width: 1.5 },
]

function pct(v) {
  return v !== null && v !== undefined ? Math.round(v * 100) : null
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="custom-tooltip">
      <div className="tt-label">Hour +{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} className="tt-row">
          <span className="tt-name" style={{ color: p.color }}>{p.name}</span>
          <span style={{ color: p.color, fontWeight: 700 }}>
            {p.value !== null ? `${p.value}%` : '—'}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function AccuracyChart({ data }) {
  // Convert scores to percentages; null values become undefined so Recharts
  // draws a gap in the line instead of a zero.
  const chartData = data.map(row => {
    const out = { hour: row.hour, count: row.count }
    LINES.forEach(({ key }) => {
      const v = pct(row[key])
      out[key] = v !== null ? v : undefined
    })
    return out
  })

  if (!chartData.length) {
    return (
      <div className="chart-wrap">
        <div className="state-box"><p>No hourly data yet.</p></div>
      </div>
    )
  }

  return (
    <div className="chart-wrap">
      <div className="chart-legend">
        {LINES.map(({ key, label, color }) => (
          <div key={key} className="legend-item">
            <div className="legend-dot" style={{ background: color }} />
            {label}
          </div>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData} margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis
            dataKey="hour"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: '#334155' }}
            label={{ value: 'Forecast hour offset', position: 'insideBottom', offset: -2, fill: '#64748b', fontSize: 11 }}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={v => `${v}%`}
            width={42}
          />
          <Tooltip content={<CustomTooltip />} />
          {LINES.map(({ key, label, color, width }) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              name={label}
              stroke={color}
              strokeWidth={width}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
