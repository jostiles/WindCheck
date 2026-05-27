/**
 * Leaderboard — sortable table of all airports ranked by accuracy.
 * Clicking a column header re-sorts. Clicking an airport row loads its detail.
 */

import { useState, useEffect } from 'react'
import { fetchLeaderboard } from '../api'

const COLUMNS = [
  { key: 'rank',                   label: '#',          sortable: false },
  { key: 'icao',                   label: 'Airport',    sortable: false },
  { key: 'observation_count',      label: 'Obs',        sortable: false },
  { key: 'overall_score',          label: 'Overall',    sortable: true  },
  { key: 'ceiling_coverage_score', label: 'Sky Cover',  sortable: true  },
  { key: 'ceiling_altitude_score', label: 'Cig Alt',    sortable: true  },
  { key: 'visibility_score',       label: 'Visibility', sortable: true  },
  { key: 'wind_speed_score',       label: 'Wind Spd',   sortable: true  },
  { key: 'wind_dir_score',         label: 'Wind Dir',   sortable: true  },
]

function ScoreCell({ value }) {
  if (value === null || value === undefined)
    return <span className="score-null">—</span>
  const pct = Math.round(value * 100)
  const color = value >= 0.8 ? '#22c55e' : value >= 0.6 ? '#f59e0b' : '#ef4444'
  return <span className="score-cell" style={{ color }}>{pct}%</span>
}

export default function Leaderboard({ onSelectAirport }) {
  const [rows,    setRows]    = useState([])
  const [sortBy,  setSortBy]  = useState('overall_score')
  const [minObs,  setMinObs]  = useState(1)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchLeaderboard(sortBy, minObs)
      .then(setRows)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [sortBy, minObs])

  function handleSort(col) {
    if (col.sortable) setSortBy(col.key)
  }

  return (
    <div>
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <div className="section-title" style={{ marginBottom: 0 }}>Airport leaderboard</div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)', marginLeft: 'auto' }}>
          Min observations
          <select
            value={minObs}
            onChange={e => setMinObs(Number(e.target.value))}
            style={{ background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6, padding: '3px 8px', fontSize: 12 }}
          >
            {[1, 3, 5, 10, 20].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="table-wrap">
        {loading
          ? <div className="state-box"><div className="spinner" /></div>
          : rows.length === 0
            ? <div className="state-box">
                <div className="state-icon">📋</div>
                <p>No airports with enough data yet.</p>
                <p className="state-hint">Run the ingest pipeline to populate the database.</p>
              </div>
            : <table>
                <thead>
                  <tr>
                    {COLUMNS.map(col => (
                      <th
                        key={col.key}
                        className={[col.sortable ? 'sortable' : '', sortBy === col.key ? 'sorted' : ''].join(' ')}
                        onClick={() => handleSort(col)}
                      >
                        {col.label}
                        {col.sortable && (
                          <span className="sort-arrow">
                            {sortBy === col.key ? ' ▼' : ' ·'}
                          </span>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={r.icao}>
                      <td className="rank-cell">{i + 1}</td>
                      <td>
                        <div
                          className="airport-link"
                          onClick={() => onSelectAirport(r.icao)}
                        >
                          {r.icao}
                        </div>
                        {r.name && (
                          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>
                            {r.name.trim()}
                          </div>
                        )}
                      </td>
                      <td style={{ color: 'var(--muted)' }}>{r.observation_count}</td>
                      <td><ScoreCell value={r.overall_score} /></td>
                      <td><ScoreCell value={r.ceiling_coverage_score} /></td>
                      <td><ScoreCell value={r.ceiling_altitude_score} /></td>
                      <td><ScoreCell value={r.visibility_score} /></td>
                      <td><ScoreCell value={r.wind_speed_score} /></td>
                      <td><ScoreCell value={r.wind_dir_score} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
        }
      </div>
    </div>
  )
}
