/**
 * RecentTable — last N scored METAR observations for an airport.
 */

function scoreColor(v) {
  if (v === null || v === undefined) return '#64748b'
  if (v >= 0.8) return '#22c55e'
  if (v >= 0.6) return '#f59e0b'
  return '#ef4444'
}

function ScoreCell({ value }) {
  if (value === null || value === undefined)
    return <span className="score-null">—</span>
  return (
    <span className="score-cell" style={{ color: scoreColor(value) }}>
      {Math.round(value * 100)}%
    </span>
  )
}

function formatTime(iso) {
  if (!iso) return '—'
  // ISO string from DB may lack timezone — treat as UTC
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toUTCString().replace(' GMT', 'Z').slice(5, 22)
}

export default function RecentTable({ rows }) {
  if (!rows?.length) return null

  return (
    <>
      <div className="section-title">Recent observations</div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time (UTC)</th>
              <th>Lead +h</th>
              <th>Category</th>
              <th>Overall</th>
              <th>Sky Cover</th>
              <th>Cig Alt</th>
              <th>Visibility</th>
              <th>Wind Spd</th>
              <th>Wind Dir</th>
              <th>TEMPO</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td style={{ fontVariantNumeric: 'tabular-nums', color: '#94a3b8' }}>
                  {formatTime(r.observation_time)}
                </td>
                <td style={{ fontVariantNumeric: 'tabular-nums' }}>
                  +{r.forecast_hour_offset.toFixed(1)}h
                </td>
                <td>
                  {r.flight_category
                    ? <span className={`fc-badge fc-${r.flight_category}`}>{r.flight_category}</span>
                    : '—'}
                </td>
                <td><ScoreCell value={r.overall_score} /></td>
                <td><ScoreCell value={r.ceiling_coverage_score} /></td>
                <td><ScoreCell value={r.ceiling_altitude_score} /></td>
                <td><ScoreCell value={r.visibility_score} /></td>
                <td><ScoreCell value={r.wind_speed_score} /></td>
                <td><ScoreCell value={r.wind_dir_score} /></td>
                <td style={{ color: r.tempo_active ? '#f59e0b' : '#334155' }}>
                  {r.tempo_active ? 'Yes' : '·'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
