/**
 * SnapshotComparison — side-by-side TAF forecast vs. METAR observed for the
 * most recent stored observation.  Gives the user a concrete, current example
 * of how scoring works.
 */

import { useState, useEffect } from 'react'
import { fetchSnapshot } from '../api'

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d)) return '—'
  return d.toUTCString().replace(' GMT', 'Z').slice(5, 22)
}

function scoreColor(v) {
  if (v === null || v === undefined) return 'var(--gray)'
  if (v >= 0.8) return '#22c55e'
  if (v >= 0.6) return '#f59e0b'
  return '#ef4444'
}

function scoreMark(v) {
  if (v === null || v === undefined) return null
  return v >= 0.8 ? '✓' : '✗'
}

function fmtCeiling(ft, cov) {
  if (ft == null) return 'Clear'
  return `${cov ?? '?'} ${ft.toLocaleString()} ft`
}

function fmtVis(sm, gt) {
  if (sm == null) return '—'
  return `${gt ? '>' : ''}${sm} SM`
}

function fmtWind(dir, spd, gust, variable) {
  if (spd == null) return '—'
  if (spd === 0) return 'Calm'
  const d = variable ? 'VRB' : `${String(dir ?? 0).padStart(3, '0')}°`
  const g = gust != null ? `G${gust}` : ''
  return `${d} @ ${spd}${g} kt`
}

function fmtWx(phenomena) {
  if (!phenomena?.length) return '—'
  return phenomena.join(' ')
}

// ── Row component ─────────────────────────────────────────────────────────────

function CompRow({ label, forecast, observed, score }) {
  const mark  = scoreMark(score)
  const color = scoreColor(score)
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td style={{ padding: '9px 14px', width: 28, textAlign: 'center' }}>
        {mark && (
          <span style={{ fontWeight: 800, color, fontSize: 13 }}>{mark}</span>
        )}
      </td>
      <td style={{ padding: '9px 14px', color: 'var(--muted)', fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', whiteSpace: 'nowrap' }}>
        {label}
      </td>
      <td style={{ padding: '9px 14px', color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
        {forecast}
      </td>
      <td style={{ padding: '9px 14px', color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
        {observed}
      </td>
    </tr>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function SnapshotComparison({ icao }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [rawOpen, setRawOpen] = useState(false)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchSnapshot(icao)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [icao])

  if (loading) return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '24px 0' }}>
      <div className="spinner" />
    </div>
  )

  if (error) return (
    <div style={{ color: 'var(--muted)', fontSize: 13, padding: '12px 0' }}>
      No snapshot available: {error}
    </div>
  )

  if (!data) return null

  const { observed, forecast, scores } = data

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, marginBottom: 24, overflow: 'hidden' }}>

      {/* Header */}
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'baseline', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px', color: 'var(--muted)' }}>
          Latest snapshot
        </div>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
          METAR <span style={{ color: 'var(--text)' }}>{formatTime(data.observation_time)}</span>
          {' · '}TAF issued <span style={{ color: 'var(--text)' }}>{formatTime(data.taf_issue_time)}</span>
          {' · '}<span style={{ color: 'var(--accent2)' }}>+{data.forecast_hour_offset}h</span> into valid period
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <span style={{
            fontSize: 18, fontWeight: 800,
            color: scoreColor(scores.overall_score),
          }}>
            {scores.overall_score != null ? `${Math.round(scores.overall_score * 100)}%` : '—'}
          </span>
          <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 4 }}>overall</span>
        </div>
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              <th style={{ padding: '8px 14px', width: 28 }} />
              <th style={{ padding: '8px 14px', textAlign: 'left', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--muted)' }}>Parameter</th>
              <th style={{ padding: '8px 14px', textAlign: 'left', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--muted)' }}>Forecast (TAF)</th>
              <th style={{ padding: '8px 14px', textAlign: 'left', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--muted)' }}>Observed (METAR)</th>
            </tr>
          </thead>
          <tbody>
            <CompRow
              label="Sky Coverage"
              forecast={forecast.ceiling_coverage ?? 'Clear'}
              observed={observed.ceiling_coverage ?? 'Clear'}
              score={scores.ceiling_coverage_score}
            />
            <CompRow
              label="Ceiling Alt"
              forecast={fmtCeiling(forecast.ceiling_ft, forecast.ceiling_coverage)}
              observed={fmtCeiling(observed.ceiling_ft, observed.ceiling_coverage)}
              score={scores.ceiling_altitude_score}
            />
            <CompRow
              label="Visibility"
              forecast={fmtVis(forecast.visibility_sm, forecast.visibility_gt)}
              observed={fmtVis(observed.visibility_sm, false)}
              score={scores.visibility_score}
            />
            <CompRow
              label="Wind"
              forecast={fmtWind(forecast.wind_dir, forecast.wind_speed, forecast.wind_gust, forecast.wind_variable)}
              observed={fmtWind(observed.wind_dir, observed.wind_speed, observed.wind_gust, observed.wind_variable)}
              score={null}
            />
            <CompRow
              label="Wind Speed"
              forecast={forecast.wind_speed != null ? `${forecast.wind_speed} kt` : '—'}
              observed={observed.wind_speed != null ? `${observed.wind_speed} kt` : '—'}
              score={scores.wind_speed_score}
            />
            <CompRow
              label="Wind Dir"
              forecast={forecast.wind_variable ? 'VRB' : forecast.wind_dir != null ? `${forecast.wind_dir}°` : '—'}
              observed={observed.wind_variable ? 'VRB' : observed.wind_dir != null ? `${observed.wind_dir}°` : '—'}
              score={scores.wind_dir_score}
            />
            <CompRow
              label="Weather"
              forecast={fmtWx(forecast.weather_phenomena)}
              observed={fmtWx(observed.weather_phenomena)}
              score={null}
            />
          </tbody>
        </table>
      </div>

      {/* Raw text toggle */}
      <div style={{ padding: '10px 18px', borderTop: '1px solid var(--border)' }}>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => setRawOpen(o => !o)}
          style={{ fontSize: 11 }}
        >
          {rawOpen ? '▲ Hide raw text' : '▼ Show raw text'}
        </button>
        {rawOpen && (
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ background: 'var(--bg)', borderRadius: 6, padding: '8px 12px', fontSize: 12, fontFamily: 'monospace', color: 'var(--muted)', wordBreak: 'break-all' }}>
              <span style={{ color: 'var(--accent2)', marginRight: 6 }}>METAR</span>{data.metar_raw}
            </div>
            <div style={{ background: 'var(--bg)', borderRadius: 6, padding: '8px 12px', fontSize: 12, fontFamily: 'monospace', color: 'var(--muted)', wordBreak: 'break-all' }}>
              <span style={{ color: 'var(--accent2)', marginRight: 6 }}>TAF</span>{data.taf_raw}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
