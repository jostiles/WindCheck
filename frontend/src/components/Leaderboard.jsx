/**
 * Leaderboard — sortable table of all airports ranked by accuracy.
 * Clicking a column header re-sorts. Clicking an airport row loads its detail.
 * Weight sliders in the header row recompute a weighted overall score client-side.
 */

import { useState, useEffect, useMemo } from 'react'
import { fetchLeaderboard, fetchStats } from '../api'

const PARAM_COLS = [
  { key: 'ceiling_coverage_score', label: 'Sky Cover'  },
  { key: 'ceiling_altitude_score', label: 'Cig Alt'    },
  { key: 'visibility_score',       label: 'Visibility' },
  { key: 'wind_speed_score',       label: 'Wind Spd'   },
  { key: 'wind_dir_score',         label: 'Wind Dir'   },
]

const DIFF_COLS = [
  { key: 'ceiling_coverage_diff', label: 'Sky Cover', unit: '/4',  fmt: v => v.toFixed(1),              greenBelow: 0.5, yellowBelow: 1.5 },
  { key: 'ceiling_altitude_diff', label: 'Cig Alt',   unit: 'ft',  fmt: v => Math.round(v).toLocaleString(), greenBelow: 500, yellowBelow: 1500 },
  { key: 'visibility_diff',       label: 'Visibility', unit: 'SM', fmt: v => v.toFixed(1),              greenBelow: 1.0, yellowBelow: 3.0  },
  { key: 'wind_speed_diff',       label: 'Wind Spd',  unit: 'kt',  fmt: v => Math.round(v),             greenBelow: 5,   yellowBelow: 15   },
  { key: 'wind_dir_diff',         label: 'Wind Dir',  unit: '°',   fmt: v => Math.round(v),             greenBelow: 20,  yellowBelow: 45   },
]

const US_STATES = [
  'AK','AL','AR','AZ','CA','CO','CT','DC','DE','FL','GA','HI','IA','ID','IL','IN',
  'KS','KY','LA','MA','MD','ME','MI','MN','MO','MS','MT','NC','ND','NE','NH','NJ',
  'NM','NV','NY','OH','OK','OR','PA','PR','RI','SC','SD','TN','TX','UT','VA','VI',
  'VT','WA','WI','WV','WY',
]

const CLIMATE_REGIONS = [
  'Northeast', 'Ohio Valley', 'Upper Midwest', 'Southeast',
  'N. Rockies & Plains', 'Southwest', 'Northwest', 'West', 'South',
  'Alaska', 'Hawaii', 'Caribbean', 'Pacific Islands',
]

const SELECT_STYLE = {
  background: 'var(--surface2)', border: '1px solid var(--border)',
  color: 'var(--text)', borderRadius: 6, padding: '3px 8px', fontSize: 12,
}

function weightedScore(row, weights) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0)
  if (total === 0) return null
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
    return <span className="score-null">—</span>
  const pct = Math.round(value * 100)
  const color = value >= 0.8 ? '#22c55e' : value >= 0.6 ? '#f59e0b' : '#ef4444'
  return <span className="score-cell" style={{ color }}>{pct}%</span>
}

function DiffCell({ value, greenBelow, yellowBelow, unit, fmt }) {
  if (value === null || value === undefined)
    return <span className="score-null">—</span>
  const color = value < greenBelow ? '#22c55e' : value < yellowBelow ? '#f59e0b' : '#ef4444'
  return <span className="score-cell" style={{ color }}>{fmt(value)}{unit !== '/4' ? ` ${unit}` : ''}</span>
}

export default function Leaderboard({ onSelectAirport, weights, setWeights, defaultWeights }) {
  const [rows,           setRows]           = useState([])
  const [minObs,         setMinObs]         = useState(1)
  const [stateFilter,    setStateFilter]    = useState('')
  const [militaryOnly,   setMilitaryOnly]   = useState(false)
  const [wfoFilter,      setWfoFilter]      = useState('')
  const [regionFilter,   setRegionFilter]   = useState('')
  const [sortAsc,        setSortAsc]        = useState(false)
  const [sortKey,        setSortKey]        = useState('overall')
  const [viewMode,       setViewMode]       = useState('score')  // 'score' | 'diff'
  const [loading,        setLoading]        = useState(false)
  const [error,          setError]          = useState(null)
  const [trackingSince,  setTrackingSince]  = useState(null)

  useEffect(() => {
    fetchStats().then(s => {
      if (s.tracking_since) {
        const d = new Date(s.tracking_since)
        setTrackingSince(d.toUTCString().replace(' GMT', 'Z').slice(5, 17))
      }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchLeaderboard('overall_score', minObs, stateFilter, militaryOnly, wfoFilter, regionFilter)
      .then(setRows)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [minObs, stateFilter, militaryOnly, wfoFilter, regionFilter])

  const isDiffMode = viewMode === 'diff'

  function handleColSort(key) {
    if (sortKey === key) {
      setSortAsc(a => !a)
    } else {
      setSortKey(key)
      // Diff columns default to ascending (lower = better); score columns descending
      const isDiffCol = DIFF_COLS.some(c => c.key === key)
      setSortAsc(isDiffCol)
    }
  }

  function switchViewMode(mode) {
    setViewMode(mode)
    if (mode === 'diff') {
      setSortKey('ceiling_coverage_diff')
      setSortAsc(true)
    } else {
      setSortKey('overall')
      setSortAsc(false)
    }
  }

  // Re-sort client-side whenever rows, weights, sortKey, or sortAsc change
  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      let va, vb
      if (sortKey === 'overall') {
        va = weightedScore(a, weights) ?? -1
        vb = weightedScore(b, weights) ?? -1
      } else if (sortKey === 'observation_count') {
        va = a.observation_count ?? 0
        vb = b.observation_count ?? 0
      } else {
        const nullVal = sortAsc ? Infinity : -1
        va = a[sortKey] ?? nullVal
        vb = b[sortKey] ?? nullVal
      }
      return sortAsc ? va - vb : vb - va
    })
  }, [rows, weights, sortAsc, sortKey])

  const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0)

  // Unique WFOs present in the current (unfiltered) result set, sorted
  const wfoOptions = useMemo(() => {
    const set = new Set(rows.map(r => r.wfo).filter(Boolean))
    return [...set].sort()
  }, [rows])

  function setWeight(key, val) {
    setWeights(prev => ({ ...prev, [key]: Math.max(0, Math.min(10, Number(val))) }))
  }

  const allEqual = Object.entries(weights).every(([k, v]) => v === defaultWeights[k])

  return (
    <div>
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <div className="section-title" style={{ marginBottom: 0 }}>Airport leaderboard</div>
          {trackingSince && (
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>
              Tracking data since {trackingSince}
            </span>
          )}
          <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
            <button
              className={`btn btn-sm${!isDiffMode ? ' btn-primary' : ' btn-ghost'}`}
              onClick={() => switchViewMode('score')}
              title="Show accuracy scores (0–100%, higher is better)"
            >
              Score
            </button>
            <button
              className={`btn btn-sm${isDiffMode ? ' btn-primary' : ' btn-ghost'}`}
              onClick={() => switchViewMode('diff')}
              title="Show average absolute difference between forecast and observed values"
            >
              Abs Diff
            </button>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginLeft: 'auto', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
            Region
            <select value={regionFilter} onChange={e => setRegionFilter(e.target.value)} style={SELECT_STYLE}>
              <option value=''>All</option>
              {CLIMATE_REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
            WFO
            <select value={wfoFilter} onChange={e => setWfoFilter(e.target.value)} style={SELECT_STYLE}>
              <option value=''>All</option>
              {wfoOptions.map(w => <option key={w} value={w}>{w}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
            State
            <select value={stateFilter} onChange={e => setStateFilter(e.target.value)} style={SELECT_STYLE}>
              <option value=''>All</option>
              {US_STATES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={militaryOnly}
              onChange={e => setMilitaryOnly(e.target.checked)}
              style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
            />
            Military only
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
            Min comparisons
            <select value={minObs} onChange={e => setMinObs(Number(e.target.value))} style={SELECT_STYLE}>
              {[1, 3, 5, 10, 20].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          {!allEqual && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setWeights(defaultWeights)}
            >
              Reset weights
            </button>
          )}
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="table-wrap">
        {loading
          ? <div className="state-box"><div className="spinner" /></div>
          : rows.length === 0
            ? <div className="state-box">
                <div className="state-icon">📋</div>
                <p>No airports with enough comparisons yet.</p>
                <p className="state-hint">Run the ingest pipeline to populate the database.</p>
              </div>
            : <table>
                <thead>
                  {/* Column headers */}
                  <tr>
                    <th>#</th>
                    <th>Airport</th>
                    <th title="NOAA Climate Region — one of 9 geographic groupings defined by the National Centers for Environmental Information (ncei.noaa.gov) based on climate similarity. Derived from the airport's state.">Region ⓘ</th>
                    <th title="Weather Forecast Office — the NWS office responsible for issuing TAFs at this location. Sourced from api.weather.gov/points using the airport's lat/lon.">WFO ⓘ</th>
                    <th>Mil</th>
                    <th
                      className="sortable"
                      style={{ cursor: 'pointer', userSelect: 'none', color: sortKey === 'observation_count' ? 'var(--accent2)' : '' }}
                      onClick={() => handleColSort('observation_count')}
                    >
                      Comp's
                      <span className="sort-arrow" style={{ fontSize: 10 }}>
                        {sortKey === 'observation_count' ? (sortAsc ? ' ▲' : ' ▼') : ' ·'}
                      </span>
                    </th>
                    {isDiffMode
                      ? DIFF_COLS.map(col => (
                          <th
                            key={col.key}
                            className="sortable"
                            style={{ cursor: 'pointer', userSelect: 'none', color: sortKey === col.key ? 'var(--accent2)' : '' }}
                            onClick={() => handleColSort(col.key)}
                          >
                            {col.label}
                            <span className="sort-arrow" style={{ fontSize: 10 }}>
                              {sortKey === col.key ? (sortAsc ? ' ▲' : ' ▼') : ' ·'}
                            </span>
                          </th>
                        ))
                      : [{ key: 'overall', label: 'Overall' }, ...PARAM_COLS].map(col => (
                          <th
                            key={col.key}
                            className="sortable"
                            style={{ cursor: 'pointer', userSelect: 'none', color: sortKey === col.key ? 'var(--accent2)' : '' }}
                            onClick={() => handleColSort(col.key)}
                          >
                            {col.label}
                            <span className="sort-arrow" style={{ fontSize: 10 }}>
                              {sortKey === col.key ? (sortAsc ? ' ▲' : ' ▼') : ' ·'}
                            </span>
                          </th>
                        ))
                    }
                  </tr>
                  {/* Weight sliders (score mode only) / units row (diff mode) */}
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    {isDiffMode ? (
                      <>
                        <th colSpan={6} style={{ padding: '6px 14px', fontWeight: 400, fontSize: 11, color: 'var(--muted)', textAlign: 'left', textTransform: 'none', letterSpacing: 0 }}>
                          Avg absolute error — lower is better
                        </th>
                        {DIFF_COLS.map(col => (
                          <th key={col.key} style={{ padding: '6px 14px', fontWeight: 400, fontSize: 10, color: 'var(--muted)', textAlign: 'center', textTransform: 'none', letterSpacing: 0 }}>
                            {col.unit === '/4' ? 'ordinal (0–4)' : col.unit}
                          </th>
                        ))}
                      </>
                    ) : (
                      <>
                        <th colSpan={6} style={{ padding: '6px 14px', fontWeight: 400, fontSize: 11, color: 'var(--muted)', textAlign: 'left', textTransform: 'none', letterSpacing: 0 }}>
                          Weights
                        </th>
                        <th style={{ padding: '6px 14px' }} />
                        {PARAM_COLS.map(col => {
                          const w = weights[col.key]
                          const pct = totalWeight > 0 ? Math.round((w / totalWeight) * 100) : 0
                          return (
                            <th key={col.key} style={{ padding: '4px 14px' }}>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'center' }}>
                                <input
                                  type="range"
                                  min={0} max={10} step={1}
                                  value={w}
                                  onChange={e => setWeight(col.key, e.target.value)}
                                  style={{ width: '100%', accentColor: 'var(--accent)', cursor: 'pointer' }}
                                />
                                <span style={{ fontSize: 10, color: w === 0 ? 'var(--gray)' : 'var(--muted)', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
                                  {w === 0 ? 'off' : `${pct}%`}
                                </span>
                              </div>
                            </th>
                          )
                        })}
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {sortedRows.map((r, i) => {
                    const ws = weightedScore(r, weights)
                    return (
                      <tr key={r.icao}>
                        <td className="rank-cell">{i + 1}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                            <div className="airport-link" onClick={() => onSelectAirport(r.icao)}>
                              {r.icao}
                            </div>
                            {r.lat != null && r.lon != null && (
                              <span style={{ fontSize: 10, color: 'var(--gray)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                                {Math.abs(r.lat).toFixed(2)}°{r.lat >= 0 ? 'N' : 'S'} {Math.abs(r.lon).toFixed(2)}°{r.lon >= 0 ? 'E' : 'W'}
                              </span>
                            )}
                          </div>
                          {r.name && (
                            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>
                              {r.name.trim()}{r.state ? `, ${r.state}` : ''}
                            </div>
                          )}
                        </td>
                        <td style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{r.climate_region ?? '—'}</td>
                        <td style={{ fontSize: 11, color: 'var(--muted)' }}>{r.wfo ?? '—'}</td>
                        <td style={{ textAlign: 'center' }}>
                          {r.is_military && (
                            <span style={{ fontSize: 10, fontWeight: 700, background: '#1e3a5f', color: '#93c5fd', borderRadius: 4, padding: '1px 5px' }}>MIL</span>
                          )}
                        </td>
                        <td style={{ color: 'var(--muted)' }}>{r.observation_count}</td>
                        {isDiffMode
                          ? DIFF_COLS.map(col => (
                              <td key={col.key}>
                                <DiffCell
                                  value={r[col.key]}
                                  greenBelow={col.greenBelow}
                                  yellowBelow={col.yellowBelow}
                                  unit={col.unit}
                                  fmt={col.fmt}
                                />
                              </td>
                            ))
                          : <>
                              <td><ScoreCell value={ws} /></td>
                              <td><ScoreCell value={r.ceiling_coverage_score} /></td>
                              <td><ScoreCell value={r.ceiling_altitude_score} /></td>
                              <td><ScoreCell value={r.visibility_score} /></td>
                              <td><ScoreCell value={r.wind_speed_score} /></td>
                              <td><ScoreCell value={r.wind_dir_score} /></td>
                            </>
                        }
                      </tr>
                    )
                  })}
                </tbody>
              </table>
        }
      </div>
    </div>
  )
}
