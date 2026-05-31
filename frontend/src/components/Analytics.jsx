/**
 * Analytics — "The real nerdy stuff" page.
 * First chart: geo-cluster scatter of all airports by lat/lon, colored by
 * NOAA climate region, sized by observation count, score shown in tooltip.
 */

import { useState, useEffect, useMemo } from 'react'
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis,
  Tooltip, Legend, ResponsiveContainer, Cell,
} from 'recharts'
import { fetchLeaderboard } from '../api'

// One distinct color per NOAA climate region
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

const REGIONS = Object.keys(REGION_COLORS)

function pct(v) { return v != null ? `${Math.round(v * 100)}%` : '—' }

function CustomTooltip({ active, payload, onSelectAirport }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  const score = d.overall_score
  const color = score == null ? '#64748b' : score >= 0.8 ? '#22c55e' : score >= 0.6 ? '#f59e0b' : '#ef4444'
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.6 }}>
      <div style={{ fontWeight: 700, fontSize: 14 }}>{d.icao}</div>
      {d.name && <div style={{ color: 'var(--muted)' }}>{d.name.trim()}{d.state ? `, ${d.state}` : ''}</div>}
      <div style={{ color, fontWeight: 700, marginTop: 4 }}>Overall: {pct(score)}</div>
      <div style={{ color: 'var(--muted)', fontSize: 11 }}>
        {d.climate_region ?? 'Unknown region'} · {d.observation_count} obs
      </div>
      <div style={{ color: 'var(--muted)', fontSize: 11 }}>
        {Math.abs(d.lat).toFixed(2)}°{d.lat >= 0 ? 'N' : 'S'} {Math.abs(d.lon).toFixed(2)}°{d.lon >= 0 ? 'E' : 'W'}
      </div>
      <div style={{ color: 'var(--accent)', fontSize: 11, marginTop: 4, cursor: 'pointer' }}
           onClick={() => onSelectAirport?.(d.icao)}>
        Click to open →
      </div>
    </div>
  )
}

function GeoCluster({ airports, onSelectAirport }) {
  const [hiddenRegions, setHiddenRegions] = useState(new Set())

  function toggleRegion(region) {
    setHiddenRegions(prev => {
      const next = new Set(prev)
      next.has(region) ? next.delete(region) : next.add(region)
      return next
    })
  }

  // Group airports by region for separate <Scatter> series (needed for legend)
  const byRegion = useMemo(() => {
    const map = {}
    for (const ap of airports) {
      if (ap.lat == null || ap.lon == null) continue
      const region = ap.climate_region ?? 'Unknown'
      if (!map[region]) map[region] = []
      map[region].push(ap)
    }
    return map
  }, [airports])

  const presentRegions = REGIONS.filter(r => byRegion[r]?.length > 0)

  return (
    <div>
      <div className="section-title">Airports by geographic cluster</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 16 }}>
        Each dot is an airport plotted at its lat/lon, colored by NOAA climate region.
        Dot size scales with observation count. Click a dot to open that airport.
      </div>

      {/* Custom legend with toggle */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', marginBottom: 12 }}>
        {presentRegions.map(region => {
          const hidden = hiddenRegions.has(region)
          return (
            <button
              key={region}
              onClick={() => toggleRegion(region)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '2px 0', fontSize: 11,
                color: hidden ? 'var(--muted)' : 'var(--text)',
                opacity: hidden ? 0.4 : 1,
              }}
            >
              <span style={{
                width: 10, height: 10, borderRadius: '50%',
                background: REGION_COLORS[region] ?? '#64748b',
                display: 'inline-block', flexShrink: 0,
              }} />
              {region} ({byRegion[region]?.length ?? 0})
            </button>
          )
        })}
      </div>

      <ResponsiveContainer width="100%" height={520}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
          <XAxis
            dataKey="lon"
            type="number"
            domain={[-180, -60]}
            name="Longitude"
            tickFormatter={v => `${Math.abs(v)}°W`}
            label={{ value: 'Longitude (west → east)', position: 'insideBottom', offset: -15, fill: 'var(--muted)', fontSize: 11 }}
            tick={{ fill: 'var(--muted)', fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
          />
          <YAxis
            dataKey="lat"
            type="number"
            domain={[15, 72]}
            name="Latitude"
            tickFormatter={v => `${v}°N`}
            label={{ value: 'Latitude', angle: -90, position: 'insideLeft', fill: 'var(--muted)', fontSize: 11 }}
            tick={{ fill: 'var(--muted)', fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
          />
          <ZAxis dataKey="observation_count" range={[20, 120]} name="Observations" />
          <Tooltip content={<CustomTooltip onSelectAirport={onSelectAirport} />} />

          {presentRegions.map(region => (
            !hiddenRegions.has(region) && (
              <Scatter
                key={region}
                name={region}
                data={byRegion[region]}
                fill={REGION_COLORS[region] ?? '#64748b'}
                fillOpacity={0.8}
                onClick={d => onSelectAirport?.(d.icao)}
                style={{ cursor: 'pointer' }}
              />
            )
          ))}
        </ScatterChart>
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

      <GeoCluster airports={airports} onSelectAirport={onSelectAirport} />
    </div>
  )
}
