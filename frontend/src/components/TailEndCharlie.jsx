/**
 * TailEndCharlie — displays the worst-scoring airport based on the current
 * leaderboard weights, with a link to view its full airport page.
 */

import { useState, useEffect, useMemo } from 'react'
import { fetchLeaderboard } from '../api'

const PARAM_COLS = [
  { key: 'ceiling_coverage_score', label: 'Sky Cover'  },
  { key: 'ceiling_altitude_score', label: 'Cig Alt'    },
  { key: 'visibility_score',       label: 'Visibility' },
  { key: 'wind_speed_score',       label: 'Wind Spd'   },
  { key: 'wind_dir_score',         label: 'Wind Dir'   },
]

function weightedScore(row, weights) {
  let sum = 0, wsum = 0
  for (const { key } of PARAM_COLS) {
    const v = row[key]
    const w = weights[key] ?? 0
    if (v != null && w > 0) { sum += v * w; wsum += w }
  }
  return wsum === 0 ? null : sum / wsum
}

function ScoreCell({ value }) {
  if (value === null || value === undefined)
    return <span style={{ color: 'var(--gray)' }}>—</span>
  const pct = Math.round(value * 100)
  const color = value >= 0.8 ? '#22c55e' : value >= 0.6 ? '#f59e0b' : '#ef4444'
  return <span style={{ color, fontWeight: 700 }}>{pct}%</span>
}

export default function TailEndCharlie({ weights, onSelectAirport }) {
  const [rows,    setRows]    = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    setLoading(true)
    fetchLeaderboard('overall_score', 5)
      .then(setRows)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const worst = useMemo(() => {
    if (!rows.length) return null
    return rows.reduce((worst, r) => {
      const ws = weightedScore(r, weights) ?? 1
      const wb = weightedScore(worst, weights) ?? 1
      return ws < wb ? r : worst
    })
  }, [rows, weights])

  const ws = worst ? weightedScore(worst, weights) : null

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '24px', marginBottom: 20 }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px', color: 'var(--muted)', marginBottom: 6 }}>
          Tail End Charlie
        </div>
        <p style={{ color: 'var(--muted)', fontSize: 13, lineHeight: 1.6, marginBottom: 20 }}>
          The worst-performing airport in the system based on your current leaderboard weights.
          Requires at least 5 observations.
        </p>

        {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}><div className="spinner" /></div>}
        {error   && <div className="error-banner">{error}</div>}

        {!loading && !error && worst && (
          <div>
            {/* Big ICAO + score */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 24, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 48, fontWeight: 800, letterSpacing: -2, color: '#ef4444', lineHeight: 1 }}>
                  {worst.icao}
                </div>
                {worst.name && (
                  <div style={{ fontSize: 14, color: 'var(--muted)', marginTop: 4 }}>{worst.name.trim()}</div>
                )}
                {worst.state && (
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>{worst.state}</div>
                )}
              </div>
              <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                <div style={{ fontSize: 40, fontWeight: 800, color: '#ef4444', lineHeight: 1 }}>
                  {ws != null ? `${Math.round(ws * 100)}%` : '—'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                  weighted overall · {worst.observation_count} obs
                </div>
              </div>
            </div>

            {/* Per-param scores */}
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
              {PARAM_COLS.map(col => (
                <div key={col.key} style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 16px', minWidth: 90 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--muted)', marginBottom: 4 }}>{col.label}</div>
                  <ScoreCell value={worst[col.key]} />
                </div>
              ))}
            </div>

            <button
              className="btn btn-primary"
              onClick={() => onSelectAirport(worst.icao)}
            >
              View {worst.icao} →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
