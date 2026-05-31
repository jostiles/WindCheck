/**
 * Analytics — "The real nerdy stuff" page.
 */

import { useState, useEffect, useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
  ReferenceLine, ResponsiveContainer,
} from 'recharts'
import { fetchLeaderboard } from '../api'

const REGION_COLORS = {
  'Northeast':           '#60a5fa',
  'Ohio Valley':         '#a78bfa',
  'Upper Midwest':       '#34d399',
  'Southeast':           '#f87171',
  'N. Rockies & Plains': '#fbbf24',
  'Southwest':           '#fb923c',
  'Northwest':           '#2dd4bf',
  'West':                '#e879f9',
  'South':               '#f472b6',
  'Alaska':              '#94a3b8',
  'Hawaii':              '#22d3ee',
  'Caribbean':           '#4ade80',
  'Pacific Islands':     '#a3e635',
}

function scoreColor(v) {
  if (v == null) return '#64748b'
  return v >= 0.8 ? '#22c55e' : v >= 0.6 ? '#f59e0b' : '#ef4444'
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.7 }}>
      <div style={{ fontWeight: 700, fontSize: 13 }}>{d.region}</div>
      <div style={{ color: scoreColor(d.score / 100), fontWeight: 700 }}>{d.score}% avg overall</div>
      <div style={{ color: 'var(--muted)' }}>{d.airports} airports · {d.obs.toLocaleString()} total obs</div>
    </div>
  )
}

function RegionScoreChart({ airports }) {
  const data = useMemo(() => {
    const map = {}
    for (const ap of airports) {
      const region = ap.climate_region ?? 'Unknown'
      if (!map[region]) map[region] = { scores: [], obs: 0, airports: 0 }
      if (ap.overall_score != null) map[region].scores.push(ap.overall_score)
      map[region].obs += ap.observation_count ?? 0
      map[region].airports++
    }
    return Object.entries(map)
      .map(([region, { scores, obs, airports }]) => ({
        region,
        score: scores.length ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 100) : null,
        obs,
        airports,
      }))
      .filter(d => d.score != null)
      .sort((a, b) => b.score - a.score)
  }, [airports])

  const avg = data.length
    ? Math.round(data.reduce((s, d) => s + d.score, 0) / data.length)
    : null

  return (
    <div>
      <div className="section-title">Average TAF accuracy by region</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        Each bar is the mean overall score across all airports in that NOAA climate region.
        {avg != null && <span> Dashed line = overall average ({avg}%).</span>}
      </div>
      <ResponsiveContainer width="100%" height={400}>
        <BarChart data={data} margin={{ top: 10, right: 20, bottom: 80, left: 0 }}>
          <XAxis
            dataKey="region"
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            angle={-35}
            textAnchor="end"
            interval={0}
          />
          <YAxis
            domain={[0, 100]}
            tickFormatter={v => `${v}%`}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          {avg != null && (
            <ReferenceLine
              y={avg}
              stroke="#64748b"
              strokeDasharray="4 3"
              label={{ value: `${avg}%`, position: 'insideTopRight', fill: '#64748b', fontSize: 11 }}
            />
          )}
          <Bar dataKey="score" radius={[4, 4, 0, 0]}>
            {data.map(d => (
              <Cell key={d.region} fill={REGION_COLORS[d.region] ?? '#64748b'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function ScoreHistogram({ airports }) {
  const data = useMemo(() => {
    const buckets = Array.from({ length: 101 }, (_, i) => ({
      label: `${i}%`,
      score: i,
      count: 0,
    }))
    for (const ap of airports) {
      if (ap.overall_score == null) continue
      const idx = Math.min(100, Math.round(ap.overall_score * 100))
      buckets[idx].count++
    }
    return buckets
  }, [airports])

  function bucketColor(score) {
    if (score >= 80) return '#22c55e'
    if (score >= 60) return '#f59e0b'
    return '#ef4444'
  }

  function HistTooltip({ active, payload }) {
    if (!active || !payload?.length) return null
    const d = payload[0]?.payload
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.7 }}>
        <div style={{ fontWeight: 700 }}>{d.score}%</div>
        <div style={{ color: 'var(--muted)' }}>{d.count} airport{d.count !== 1 ? 's' : ''}</div>
      </div>
    )
  }

  return (
    <div style={{ marginTop: 40 }}>
      <div className="section-title">Score distribution across all airports</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        How many airports fall into each 5-point score bucket.
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 0 }}>
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--muted)', fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            interval={9}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            label={{ value: 'Airports', angle: -90, position: 'insideLeft', fill: 'var(--muted)', fontSize: 11 }}
          />
          <Tooltip content={<HistTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="count" radius={[3, 3, 0, 0]}>
            {data.map(d => (
              <Cell key={d.score} fill={bucketColor(d.score)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function Analytics({ onSelectAirport }) {
  const [airports, setAirports] = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)

  useEffect(() => {
    fetchLeaderboard('overall_score', 1)
      .then(setAirports)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="state-box" style={{ paddingTop: 80 }}>
      <div className="spinner" />
    </div>
  )

  if (error) return (
    <div className="error-banner">Could not load data: {error}</div>
  )

  return (
    <div>
      <div className="section-title" style={{ fontSize: 20, marginBottom: 4 }}>The real nerdy stuff</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 28 }}>
        Data analytics across all {airports.length} tracked airports.
      </div>

      <RegionScoreChart airports={airports} />
      <ScoreHistogram airports={airports} />
    </div>
  )
}
