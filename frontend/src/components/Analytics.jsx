/**
 * Analytics — "The real nerdy stuff" page.
 */

import { useState, useEffect, useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
  ReferenceLine, ResponsiveContainer,
} from 'recharts'
import { fetchAnalytics } from '../api'

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

// ── OLS regression helpers ────────────────────────────────────────────────
// Implements β = (X'X)⁻¹ X'y via Gaussian elimination (no external library).

function matMul(A, B) {
  const rows = A.length, cols = B[0].length, inner = B.length
  return Array.from({ length: rows }, (_, i) =>
    Array.from({ length: cols }, (_, j) =>
      Array.from({ length: inner }, (_, k) => A[i][k] * B[k][j])
        .reduce((s, v) => s + v, 0)
    )
  )
}

function matT(A) {
  return A[0].map((_, j) => A.map(row => row[j]))
}

function matInv(M) {
  const n = M.length
  const aug = M.map((row, i) => [...row, ...Array.from({ length: n }, (_, j) => i === j ? 1 : 0)])
  for (let col = 0; col < n; col++) {
    let pivot = col
    for (let row = col + 1; row < n; row++)
      if (Math.abs(aug[row][col]) > Math.abs(aug[pivot][col])) pivot = row;
    [aug[col], aug[pivot]] = [aug[pivot], aug[col]]
    const d = aug[col][col]
    if (Math.abs(d) < 1e-12) return null
    aug[col] = aug[col].map(v => v / d)
    for (let row = 0; row < n; row++) {
      if (row === col) continue
      const f = aug[row][col]
      aug[row] = aug[row].map((v, k) => v - f * aug[col][k])
    }
  }
  return aug.map(row => row.slice(n))
}

function ols(X, y) {
  const Xt  = matT(X)
  const XtX = matMul(Xt, X)
  const inv = matInv(XtX)
  if (!inv) return null
  const Xty = matMul(Xt, y.map(v => [v]))
  const beta = matMul(inv, Xty).map(r => r[0])

  // R²
  const yMean = y.reduce((s, v) => s + v, 0) / y.length
  const yHat  = X.map(row => row.reduce((s, x, i) => s + x * beta[i], 0))
  const ssTot = y.reduce((s, v) => s + (v - yMean) ** 2, 0)
  const ssRes = y.reduce((s, v, i) => s + (v - yHat[i]) ** 2, 0)
  const r2    = ssTot > 0 ? 1 - ssRes / ssTot : 0

  return { beta, r2 }
}

const REGIONS_ORDER = [
  'Northeast', 'Ohio Valley', 'Upper Midwest', 'Southeast',
  'N. Rockies & Plains', 'Southwest', 'Northwest', 'West',
  'South', 'Alaska', 'Hawaii', 'Caribbean', 'Pacific Islands',
]
// baseline region = 'Northeast' (omitted for dummy coding)
const DUMMY_REGIONS = REGIONS_ORDER.slice(1)

function ObsHistogram({ airports }) {
  const data = useMemo(() => {
    if (!airports.length) return []
    const size = 5
    const buckets = {}
    for (const ap of airports) {
      const b = Math.floor(ap.observation_count / size) * size
      if (!buckets[b]) buckets[b] = { civilian: 0, military: 0 }
      if (ap.is_military) buckets[b].military++
      else buckets[b].civilian++
    }
    return Object.entries(buckets)
      .map(([b, { civilian, military }]) => ({
        bucket: Number(b), label: `${b}`, civilian, military,
      }))
      .sort((a, b) => a.bucket - b.bucket)
  }, [airports])

  function ObsTooltip({ active, payload }) {
    if (!active || !payload?.length) return null
    const d = payload[0]?.payload
    const total = d.civilian + d.military
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.7 }}>
        <div style={{ fontWeight: 700 }}>{d.bucket}–{d.bucket + 4} observations</div>
        <div style={{ color: '#60a5fa' }}>Civilian: {d.civilian}</div>
        {d.military > 0 && <div style={{ color: '#fbbf24' }}>Military: {d.military}</div>}
        <div style={{ color: 'var(--muted)' }}>Total: {total}</div>
      </div>
    )
  }

  return (
    <div style={{ marginTop: 40 }}>
      <div className="section-title">Observation count distribution</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        <span>How many airports have each number of scored observations.</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: '#60a5fa', display: 'inline-block' }} /> Civilian
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: '#fbbf24', display: 'inline-block' }} /> Military
        </span>
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 0 }} stackOffset="none">
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--muted)', fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            interval="preserveStartEnd"
            label={{ value: 'Observations', position: 'insideBottom', offset: -10, fill: 'var(--muted)', fontSize: 11 }}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            label={{ value: 'Airports', angle: -90, position: 'insideLeft', fill: 'var(--muted)', fontSize: 11 }}
          />
          <Tooltip content={<ObsTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="civilian" stackId="a" fill="#60a5fa" />
          <Bar dataKey="military" stackId="a" fill="#fbbf24" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function RegressionTable({ airports }) {
  const result = useMemo(() => {
    const rows = airports.filter(ap =>
      ap.overall_score != null &&
      ap.amendment_pct != null &&
      ap.wfo != null
    )
    if (rows.length < 10) return null

    const meanAmd = rows.reduce((s, r) => s + r.amendment_pct, 0) / rows.length

    // WFO dummies — only WFOs with 2+ airports, sorted; first WFO = baseline
    const wfoCounts = {}
    for (const r of rows) wfoCounts[r.wfo] = (wfoCounts[r.wfo] || 0) + 1
    const allWfos = Object.keys(wfoCounts).sort()
    const [baselineWfo, ...dummyWfos] = allWfos

    const X = rows.map(r => [
      1,                                                          // intercept
      r.amendment_pct - meanAmd,                                  // amendment rate (centered)
      r.is_military ? 1 : 0,                                      // military (binary)
      ...dummyWfos.map(wfo => r.wfo === wfo ? 1 : 0),            // WFO dummies
    ])
    const y = rows.map(r => r.overall_score * 100)

    const fit = ols(X, y)
    if (!fit) return null

    const labels = [
      'Intercept',
      'Amendment rate (per 1%)',
      'Military airport',
      ...dummyWfos.map(w => `WFO: ${w}`),
    ]

    return {
      n: rows.length,
      r2: fit.r2,
      meanAmd,
      baselineWfo,
      coefficients: labels.map((label, i) => ({ label, beta: fit.beta[i] })),
    }
  }, [airports])

  if (!result) return (
    <div className="state-box" style={{ padding: '32px 24px' }}>
      <p>Not enough data for regression.</p>
    </div>
  )

  const { n, r2, coefficients, baselineWfo } = result
  const maxAbs = Math.max(...coefficients.slice(1).map(c => Math.abs(c.beta)))

  return (
    <div style={{ marginTop: 40 }}>
      <div className="section-title">Multiple linear regression: predictors of overall score</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
        OLS regression with <strong style={{ color: 'var(--text)' }}>overall score (0–100%)</strong> as the outcome.
        Continuous variables are mean-centered. WFO baseline = {result.baselineWfo}.
        n = {n} airports.
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        R² = <strong style={{ color: 'var(--text)' }}>{(r2 * 100).toFixed(1)}%</strong> of variance explained.
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              <th style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--muted)', fontWeight: 600 }}>Predictor</th>
              <th style={{ textAlign: 'right', padding: '6px 12px', color: 'var(--muted)', fontWeight: 600 }}>Coefficient (pp)</th>
              <th style={{ padding: '6px 12px', color: 'var(--muted)', fontWeight: 600, width: 200 }}>Effect size</th>
            </tr>
          </thead>
          <tbody>
            {coefficients.map(({ label, beta }, i) => {
              const isIntercept = i === 0
              const barWidth = isIntercept ? 0 : Math.round((Math.abs(beta) / maxAbs) * 100)
              const barColor = beta >= 0 ? '#22c55e' : '#ef4444'
              return (
                <tr key={label} style={{ borderBottom: '1px solid var(--border)', opacity: isIntercept ? 0.5 : 1 }}>
                  <td style={{ padding: '7px 12px', color: 'var(--text)' }}>{label}</td>
                  <td style={{ padding: '7px 12px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: isIntercept ? 'var(--muted)' : beta >= 0 ? '#22c55e' : '#ef4444', fontWeight: isIntercept ? 400 : 600 }}>
                    {beta >= 0 && !isIntercept ? '+' : ''}{beta.toFixed(2)}
                  </td>
                  <td style={{ padding: '7px 12px' }}>
                    {!isIntercept && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{ flex: 1, height: 8, background: 'var(--surface2)', borderRadius: 4, overflow: 'hidden' }}>
                          <div style={{ width: `${barWidth}%`, height: '100%', background: barColor, borderRadius: 4 }} />
                        </div>
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 10 }}>
        Coefficients are in percentage points. E.g. +2.5 means that factor is associated with a 2.5 pp higher score, holding all others constant.
      </div>
    </div>
  )
}

export default function Analytics({ onSelectAirport }) {
  const [airports, setAirports] = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)

  useEffect(() => {
    fetchAnalytics()
      .then(setAirports)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="state-box" style={{ paddingTop: 80 }}>
      <div className="spinner" />
      <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 12 }}>
        Crunching data across all airports — first load may take up to 30 seconds.
      </p>
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
      <ObsHistogram airports={airports} />
      <RegressionTable airports={airports} />
    </div>
  )
}
