/**
 * MapView — interactive map of all graded US airports colored by overall
 * TAF accuracy score.  Click a marker to see the airport name and score;
 * click the ICAO link to open the airport detail view.
 */

import { useState, useEffect } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { fetchMapData } from '../api'

function scoreColor(v) {
  if (v === null || v === undefined) return '#64748b'
  if (v >= 0.8) return '#22c55e'
  if (v >= 0.6) return '#f59e0b'
  return '#ef4444'
}

function scorePct(v) {
  return v != null ? `${Math.round(v * 100)}%` : '—'
}

export default function MapView({ onSelectAirport }) {
  const [airports, setAirports] = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)

  useEffect(() => {
    fetchMapData()
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
    <div className="error-banner">Could not load map data: {error}</div>
  )

  if (!airports.length) return (
    <div className="state-box">
      <div className="state-icon">🗺️</div>
      <p>No airport data yet.</p>
      <p className="state-hint">Run the ingest pipeline to populate the map.</p>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 20, fontSize: 12, color: 'var(--muted)', flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 700, color: 'var(--text)' }}>{airports.length} airports</span>
        {[['#22c55e', '≥ 80% Good'], ['#f59e0b', '60–79% Fair'], ['#ef4444', '< 60% Poor'], ['#64748b', 'No data']].map(([color, label]) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0 }} />
            {label}
          </span>
        ))}
      </div>

      {/* Map */}
      <div style={{ borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)', height: 560 }}>
        <MapContainer
          center={[39, -98]}
          zoom={4}
          style={{ height: '100%', width: '100%', background: '#0f172a' }}
          zoomControl={true}
        >
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            attribution='&copy; <a href="https://carto.com/">CARTO</a>'
            maxZoom={19}
          />

          {airports.map(ap => (
            <CircleMarker
              key={ap.icao}
              center={[ap.lat, ap.lon]}
              radius={5}
              pathOptions={{
                fillColor:   scoreColor(ap.overall_score),
                fillOpacity: 0.85,
                color:       '#0f172a',
                weight:      1,
              }}
              eventHandlers={{
                click: () => onSelectAirport(ap.icao),
              }}
            >
              <Tooltip direction="top" offset={[0, -6]} opacity={0.95}>
                <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                  <div style={{ fontWeight: 700 }}>{ap.icao}</div>
                  {ap.name && <div style={{ color: '#94a3b8', maxWidth: 160 }}>{ap.name.trim()}</div>}
                  <div style={{ color: scoreColor(ap.overall_score), fontWeight: 700, marginTop: 2 }}>
                    {scorePct(ap.overall_score)}
                  </div>
                  <div style={{ color: '#64748b', fontSize: 11 }}>{ap.observation_count} obs · click to open</div>
                </div>
              </Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
    </div>
  )
}
