/**
 * MetricsGrid — five score cards showing overall + per-parameter accuracy.
 */

const METRICS = [
  { key: 'overall_score',          label: 'Overall',      color: '#6366f1' },
  { key: 'ceiling_coverage_score', label: 'Sky Coverage', color: '#0ea5e9' },
  { key: 'ceiling_altitude_score', label: 'Ceiling Alt',  color: '#38bdf8' },
  { key: 'visibility_score',       label: 'Visibility',   color: '#f59e0b' },
  { key: 'wind_speed_score',       label: 'Wind Speed',   color: '#10b981' },
  { key: 'wind_dir_score',         label: 'Wind Dir',     color: '#f43f5e' },
]

function scoreColor(v) {
  if (v === null || v === undefined) return '#64748b'
  if (v >= 0.8) return '#22c55e'
  if (v >= 0.6) return '#f59e0b'
  return '#ef4444'
}

function ScoreCard({ label, value, color, count }) {
  const display = value !== null && value !== undefined
    ? `${Math.round(value * 100)}%`
    : '—'

  return (
    <div className="metric-card" style={{ borderTopColor: color }}>
      <div className="metric-label">{label}</div>
      <div
        className="metric-value"
        style={{ color: value !== null ? scoreColor(value) : '#64748b' }}
      >
        {display}
      </div>
      {count !== undefined && (
        <div className="metric-count">{count} obs</div>
      )}
    </div>
  )
}

export default function MetricsGrid({ summary }) {
  return (
    <div className="metrics-grid">
      {METRICS.map(({ key, label, color }) => (
        <ScoreCard
          key={key}
          label={label}
          color={color}
          value={summary[key]}
          count={key === 'overall_score' ? summary.observation_count : undefined}
        />
      ))}
    </div>
  )
}
