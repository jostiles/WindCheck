/**
 * Analytics — "The real nerdy stuff" page.
 */

import { useState, useEffect, useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
  ReferenceLine, ResponsiveContainer,
  ScatterChart, Scatter, ZAxis,
  LineChart, Line, Legend,
} from 'recharts'
import { fetchAnalytics, fetchLeadTime, fetchDailyComparisons } from '../api'

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

// ── Stats helpers ─────────────────────────────────────────────────────────

function gMean(arr) { return arr.reduce((s, v) => s + v, 0) / arr.length }
function gSD(arr) {
  if (arr.length < 2) return 0
  const m = gMean(arr)
  return Math.sqrt(arr.reduce((s, v) => s + (v - m) ** 2, 0) / (arr.length - 1))
}
// Normal CDF (Hart approximation, accurate to ~1e-7)
function normCDF(z) {
  const a = [0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429]
  const k = 1 / (1 + 0.2316419 * Math.abs(z))
  let poly = 0; for (let i = 4; i >= 0; i--) poly = poly * k + a[i]; poly *= k
  const p = 1 - (1 / Math.sqrt(2 * Math.PI)) * Math.exp(-z * z / 2) * poly
  return z >= 0 ? p : 1 - p
}
function pFromT(t) { return 2 * (1 - normCDF(Math.abs(t))) }
function fmtP(p) { return p < 0.001 ? '< 0.001' : p < 0.01 ? p.toFixed(3) : p.toFixed(2) }
function effectLabel(d) {
  const a = Math.abs(d)
  return a < 0.2 ? 'negligible' : a < 0.5 ? 'small' : a < 0.8 ? 'medium' : 'large'
}
function effectColor(d) {
  const a = Math.abs(d)
  return a < 0.2 ? 'var(--muted)' : a < 0.5 ? '#f59e0b' : '#ef4444'
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
  const residuals = y.map((v, i) => v - yHat[i])

  return { beta, r2, yHat, residuals }
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

function PredictedVsActualChart({ points }) {
  function ScatterTooltip({ active, payload }) {
    if (!active || !payload?.length) return null
    const d = payload[0]?.payload
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.7 }}>
        <div style={{ fontWeight: 700 }}>{d.icao}</div>
        <div style={{ color: 'var(--muted)' }}>{d.region}</div>
        <div>Actual: <strong>{d.actual.toFixed(1)}%</strong></div>
        <div>Predicted: <strong>{d.predicted.toFixed(1)}%</strong></div>
        <div style={{ color: d.residual >= 0 ? '#22c55e' : '#ef4444' }}>
          Residual: {d.residual >= 0 ? '+' : ''}{d.residual.toFixed(1)} % pts
        </div>
      </div>
    )
  }

  // Group by region for coloring
  const byRegion = {}
  for (const p of points) {
    if (!byRegion[p.region]) byRegion[p.region] = []
    byRegion[p.region].push(p)
  }

  // axis range
  const allVals = points.flatMap(p => [p.predicted, p.actual])
  const lo = Math.floor(Math.min(...allVals) / 5) * 5
  const hi = Math.ceil(Math.max(...allVals) / 5) * 5

  return (
    <div style={{ marginTop: 40 }}>
      <div className="section-title">Predicted vs. actual score</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        Each dot is one airport. Points above the diagonal are better than the model predicts; below are worse.
      </div>
      <ResponsiveContainer width="100%" height={400}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 40, left: 0 }}>
          <XAxis
            type="number" dataKey="predicted"
            name="Predicted"
            domain={[lo, hi]}
            tickFormatter={v => `${v}%`}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            label={{ value: 'Predicted score (%)', position: 'insideBottom', offset: -20, fill: 'var(--muted)', fontSize: 11 }}
          />
          <YAxis
            type="number" dataKey="actual"
            name="Actual"
            domain={[lo, hi]}
            tickFormatter={v => `${v}%`}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            label={{ value: 'Actual score (%)', angle: -90, position: 'insideLeft', fill: 'var(--muted)', fontSize: 11 }}
          />
          <ZAxis range={[30, 30]} />
          <Tooltip content={<ScatterTooltip />} cursor={{ strokeDasharray: '3 3' }} />
          <ReferenceLine
            segment={[{ x: lo, y: lo }, { x: hi, y: hi }]}
            stroke="#64748b" strokeDasharray="4 3"
          />
          {Object.entries(byRegion).map(([region, pts]) => (
            <Scatter
              key={region}
              name={region}
              data={pts}
              fill={REGION_COLORS[region] ?? '#64748b'}
              fillOpacity={0.75}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

function ResidualsHistogram({ residuals }) {
  const data = useMemo(() => {
    if (!residuals.length) return []
    const size = 2 // 2 % pts bins
    const buckets = {}
    for (const r of residuals) {
      const b = Math.floor(r / size) * size
      buckets[b] = (buckets[b] || 0) + 1
    }
    return Object.entries(buckets)
      .map(([b, count]) => ({ bucket: Number(b), label: `${Number(b) >= 0 ? '+' : ''}${b}`, count }))
      .sort((a, b) => a.bucket - b.bucket)
  }, [residuals])

  const mean = residuals.length ? residuals.reduce((s, v) => s + v, 0) / residuals.length : 0

  function ResTooltip({ active, payload }) {
    if (!active || !payload?.length) return null
    const d = payload[0]?.payload
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.7 }}>
        <div style={{ fontWeight: 700 }}>{d.label} to {d.bucket >= 0 ? '+' : ''}{d.bucket + 2} % pts</div>
        <div style={{ color: 'var(--muted)' }}>{d.count} airport{d.count !== 1 ? 's' : ''}</div>
      </div>
    )
  }

  return (
    <div style={{ marginTop: 40 }}>
      <div className="section-title">Residuals distribution</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        Actual − predicted score for each airport. A well-fitting model produces residuals centered near zero with no strong skew.
        Mean residual = <strong style={{ color: 'var(--text)' }}>{mean >= 0 ? '+' : ''}{mean.toFixed(2)} % pts</strong>.
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 10, right: 20, bottom: 30, left: 0 }}>
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--muted)', fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            interval="preserveStartEnd"
            label={{ value: 'Residual (pp)', position: 'insideBottom', offset: -15, fill: 'var(--muted)', fontSize: 11 }}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            label={{ value: 'Airports', angle: -90, position: 'insideLeft', fill: 'var(--muted)', fontSize: 11 }}
          />
          <Tooltip content={<ResTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <ReferenceLine x="0" stroke="#64748b" strokeDasharray="4 3" />
          <Bar dataKey="count" radius={[3, 3, 0, 0]}>
            {data.map(d => (
              <Cell key={d.bucket} fill={d.bucket >= 0 ? '#22c55e' : '#ef4444'} fillOpacity={0.8} />
            ))}
          </Bar>
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
      ap.climate_region != null
    )
    if (rows.length < 10) return null

    const meanAmd = rows.reduce((s, r) => s + r.amendment_pct, 0) / rows.length

    // Region dummies — only include regions actually present in data (avoids zero columns)
    const presentRegions = new Set(rows.map(r => r.climate_region))
    const activeDummies = DUMMY_REGIONS.filter(r => presentRegions.has(r))
    // baseline = Northeast (or first in REGIONS_ORDER that is present)
    const baseline = REGIONS_ORDER.find(r => presentRegions.has(r)) ?? REGIONS_ORDER[0]

    const X = rows.map(r => [
      1,                                                                  // intercept
      r.amendment_pct - meanAmd,                                          // amendment rate (centered)
      r.is_military ? 1 : 0,                                              // military (binary)
      ...activeDummies.map(region => r.climate_region === region ? 1 : 0), // region dummies
    ])
    const y = rows.map(r => r.overall_score * 100)

    const fit = ols(X, y)
    if (!fit) return null

    const labels = [
      'Intercept',
      'Amendment rate (per 1%)',
      'Military airport',
      ...activeDummies.map(r => `Region: ${r}`),
    ]

    const scatterPoints = rows.map((r, i) => ({
      icao: r.icao,
      region: r.climate_region,
      predicted: fit.yHat[i],
      actual: y[i],
      residual: fit.residuals[i],
    }))

    return {
      n: rows.length,
      r2: fit.r2,
      baseline,
      coefficients: labels.map((label, i) => ({ label, beta: fit.beta[i] })),
      scatterPoints,
      residuals: fit.residuals,
    }
  }, [airports])

  if (!result) return (
    <div className="state-box" style={{ padding: '32px 24px' }}>
      <p>Not enough data for regression.</p>
    </div>
  )

  const { n, r2, coefficients, baseline, scatterPoints, residuals } = result
  const maxAbs = Math.max(...coefficients.slice(1).map(c => Math.abs(c.beta)))

  return (
    <div style={{ marginTop: 40 }}>
      <div className="section-title">Multiple linear regression: predictors of overall score</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
        OLS regression with <strong style={{ color: 'var(--text)' }}>overall score (0–100%)</strong> as the outcome.
        Continuous variables are mean-centered. Region baseline = {baseline}.
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
        Coefficients are in % pts. E.g. +2.5 means that factor is associated with a 2.5 % pts higher score, holding all others constant.
      </div>

      <PredictedVsActualChart points={scatterPoints} />
      <ResidualsHistogram residuals={residuals} />
    </div>
  )
}

const ELEMENT_LINES = [
  { key: 'overall',     label: 'Overall',    color: '#e2e8f0', width: 2.5 },
  { key: 'ceiling_cov', label: 'Ceiling coverage', color: '#60a5fa', width: 1.5 },
  { key: 'ceiling_alt', label: 'Ceiling altitude',  color: '#a78bfa', width: 1.5 },
  { key: 'visibility',  label: 'Visibility',  color: '#34d399', width: 1.5 },
  { key: 'wind_spd',    label: 'Wind speed',  color: '#fbbf24', width: 1.5 },
  { key: 'wind_dir',    label: 'Wind dir',    color: '#fb923c', width: 1.5 },
]

function LeadTimeDecayChart({ data }) {
  if (!data.length) return null

  function LTTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null
    const row = data.find(d => d.hour === label)
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.8 }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>+{label}h lead time</div>
        {payload.map(p => (
          <div key={p.dataKey} style={{ color: p.color }}>
            {ELEMENT_LINES.find(l => l.key === p.dataKey)?.label}: <strong>{p.value?.toFixed(1)}%</strong>
          </div>
        ))}
        {row && <div style={{ color: 'var(--muted)', marginTop: 4 }}>{row.n.toLocaleString()} comparisons</div>}
      </div>
    )
  }

  return (
    <div style={{ marginTop: 40 }}>
      <div className="section-title">Accuracy decay by forecast lead time</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        Average score vs. hours between TAF issuance and the observation being scored.
        Longer lead times = forecast was made further in advance. Scores are expected to decline with distance.
      </div>
      <ResponsiveContainer width="100%" height={360}>
        <LineChart data={data} margin={{ top: 10, right: 20, bottom: 30, left: 0 }}>
          <XAxis
            dataKey="hour"
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            label={{ value: 'Lead time (hours)', position: 'insideBottom', offset: -15, fill: 'var(--muted)', fontSize: 11 }}
          />
          <YAxis
            domain={[50, 100]}
            tickFormatter={v => `${v}%`}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<LTTooltip />} />
          <Legend
            verticalAlign="top"
            wrapperStyle={{ fontSize: 11, paddingBottom: 8 }}
            formatter={(value) => ELEMENT_LINES.find(l => l.key === value)?.label ?? value}
          />
          {ELEMENT_LINES.map(({ key, color, width }) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={color}
              strokeWidth={width}
              dot={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function DailyComparisonsChart({ data }) {
  if (!data.length) return null

  function DCTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.7 }}>
        <div style={{ fontWeight: 700 }}>{label}</div>
        <div style={{ color: '#60a5fa' }}>{payload[0]?.value?.toLocaleString()} comparisons</div>
      </div>
    )
  }

  // Only label the first of each month on the x-axis
  const ticks = data
    .filter(d => d.date.endsWith('-01'))
    .map(d => d.date)

  return (
    <div style={{ marginTop: 40 }}>
      <div className="section-title">Daily comparisons over time</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        Number of scored TAF-vs-METAR comparisons per day across all airports.
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 10, right: 20, bottom: 30, left: 0 }}>
          <XAxis
            dataKey="date"
            ticks={ticks}
            tick={{ fill: 'var(--muted)', fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            tickFormatter={d => d.slice(0, 7)}
          />
          <YAxis
            allowDecimals={false}
            tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}k` : v}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<DCTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="comparisons" fill="#60a5fa" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Military vs. Civilian Analysis ───────────────────────────────────────

const MIL_COMPONENTS = [
  { key: 'overall_score',          label: 'Overall' },
  { key: 'ceiling_coverage_score', label: 'Ceiling coverage' },
  { key: 'ceiling_altitude_score', label: 'Ceiling altitude' },
  { key: 'visibility_score',       label: 'Visibility' },
  { key: 'wind_speed_score',       label: 'Wind speed' },
  { key: 'wind_dir_score',         label: 'Wind dir' },
]

function MilitaryAnalysis({ airports }) {
  const result = useMemo(() => {
    const mil = airports.filter(ap => ap.is_military && ap.overall_score != null)
    const civ = airports.filter(ap => !ap.is_military && ap.overall_score != null)
    if (mil.length < 3 || civ.length < 3) return null

    const stats = MIL_COMPONENTS.map(({ key, label }) => {
      const ms = mil.map(ap => ap[key]).filter(v => v != null).map(v => v * 100)
      const cs = civ.map(ap => ap[key]).filter(v => v != null).map(v => v * 100)
      if (!ms.length || !cs.length) return null
      const mm = gMean(ms), cm = gMean(cs)
      const msd = gSD(ms), csd = gSD(cs)
      const vm = msd ** 2 / ms.length, vc = csd ** 2 / cs.length
      const t = (cm - mm) / Math.sqrt(vm + vc)
      const pooledSD = Math.sqrt(((ms.length - 1) * msd ** 2 + (cs.length - 1) * csd ** 2) / (ms.length + cs.length - 2))
      const d = pooledSD > 0 ? (cm - mm) / pooledSD : 0  // positive = civilian better
      const p = pFromT(t)
      return { key, label, milMean: mm, civMean: cm, gap: cm - mm, d, p, milN: ms.length, civN: cs.length }
    }).filter(Boolean)

    // OLS model 1: score ~ military only
    const rows = airports.filter(ap => ap.overall_score != null)
    const y = rows.map(ap => ap.overall_score * 100)
    const X1 = rows.map(ap => [1, ap.is_military ? 1 : 0])
    const fit1 = ols(X1, y)

    // OLS model 2: score ~ military + region dummies
    const rowsR = airports.filter(ap => ap.overall_score != null && ap.climate_region != null)
    const yR = rowsR.map(ap => ap.overall_score * 100)
    const presentRegions = new Set(rowsR.map(r => r.climate_region))
    const activeDummies = DUMMY_REGIONS.filter(r => presentRegions.has(r))
    const X2 = rowsR.map(ap => [
      1, ap.is_military ? 1 : 0,
      ...activeDummies.map(r => ap.climate_region === r ? 1 : 0),
    ])
    const fit2 = ols(X2, yR)

    // Distribution: 5-point buckets for overall score
    const distBuckets = {}
    for (const ap of airports) {
      if (ap.overall_score == null) continue
      const b = Math.floor(ap.overall_score * 100 / 5) * 5
      if (!distBuckets[b]) distBuckets[b] = { military: 0, civilian: 0 }
      if (ap.is_military) distBuckets[b].military++
      else distBuckets[b].civilian++
    }
    const distData = Object.entries(distBuckets)
      .map(([b, v]) => ({ bucket: Number(b), label: `${b}%`, ...v }))
      .sort((a, b) => a.bucket - b.bucket)

    return {
      stats,
      milN: mil.length,
      civN: civ.length,
      milObs: mil.reduce((s, ap) => s + (ap.observation_count ?? 0), 0),
      civObs: civ.reduce((s, ap) => s + (ap.observation_count ?? 0), 0),
      rawCoeff:  fit1  ? fit1.beta[1]  : null,
      adjCoeff:  fit2  ? fit2.beta[1]  : null,
      distData,
    }
  }, [airports])

  if (!result) return (
    <div className="state-box" style={{ padding: '32px 24px' }}>
      <p>Not enough data for military analysis.</p>
    </div>
  )

  const { stats, milN, civN, milObs, civObs, rawCoeff, adjCoeff, distData } = result
  const overall = stats[0]

  // Chart data for grouped bars
  const barData = stats.map(s => ({
    label: s.label,
    Military: +s.milMean.toFixed(1),
    Civilian: +s.civMean.toFixed(1),
  }))

  function MilCompTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null
    const s = stats.find(s => s.label === label)
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.8 }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>
        <div style={{ color: '#60a5fa' }}>Civilian: <strong>{payload.find(p => p.dataKey === 'Civilian')?.value?.toFixed(1)}%</strong></div>
        <div style={{ color: '#fbbf24' }}>Military: <strong>{payload.find(p => p.dataKey === 'Military')?.value?.toFixed(1)}%</strong></div>
        {s && <div style={{ color: s.gap >= 0 ? '#ef4444' : '#22c55e', marginTop: 4 }}>
          Gap: {s.gap >= 0 ? '+' : ''}{s.gap.toFixed(1)} % pts · Cohen's d = {s.d.toFixed(2)} ({effectLabel(s.d)})
        </div>}
      </div>
    )
  }

  function DistTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null
    const mil = payload.find(p => p.dataKey === 'military')?.value ?? 0
    const civ = payload.find(p => p.dataKey === 'civilian')?.value ?? 0
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12, lineHeight: 1.8 }}>
        <div style={{ fontWeight: 700 }}>{label}–{Number(label) + 5}%</div>
        <div style={{ color: '#60a5fa' }}>Civilian: {civ} airports</div>
        <div style={{ color: '#fbbf24' }}>Military: {mil} airports</div>
      </div>
    )
  }

  const civMilDomain = [
    Math.floor(Math.min(...barData.flatMap(d => [d.Military, d.Civilian])) / 5) * 5 - 5,
    Math.ceil( Math.max(...barData.flatMap(d => [d.Military, d.Civilian])) / 5) * 5 + 2,
  ]

  return (
    <div>
      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 32 }}>
        {[
          { label: 'Military airports', n: milN, obs: milObs, color: '#fbbf24' },
          { label: 'Civilian airports', n: civN, obs: civObs, color: '#60a5fa' },
        ].map(({ label, n, obs, color }) => (
          <div key={label} style={{ background: 'var(--surface)', border: `1px solid ${color}33`, borderRadius: 10, padding: '16px 20px' }}>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, color }}>{n}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{obs.toLocaleString()} total observations</div>
          </div>
        ))}
      </div>

      {/* Key finding */}
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: '18px 22px', marginBottom: 32, fontSize: 13, lineHeight: 1.8 }}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8 }}>Key findings</div>
        <div>
          Raw gap: military fields score{' '}
          <strong style={{ color: overall.gap >= 0 ? '#ef4444' : '#22c55e' }}>
            {overall.gap >= 0 ? '' : '+'}{(-overall.gap).toFixed(1)} % pts {overall.gap >= 0 ? 'lower' : 'higher'}
          </strong>{' '}
          than civilian (p {fmtP(overall.p)}, Cohen's d = {overall.d.toFixed(2)} — <em>{effectLabel(overall.d)}</em> effect).
        </div>
        {adjCoeff != null && rawCoeff != null && (
          <div style={{ marginTop: 6 }}>
            After controlling for climate region: military coefficient changes from{' '}
            <strong style={{ color: rawCoeff >= 0 ? '#22c55e' : '#ef4444' }}>{rawCoeff >= 0 ? '+' : ''}{rawCoeff.toFixed(2)} % pts</strong>{' '}
            to{' '}
            <strong style={{ color: adjCoeff >= 0 ? '#22c55e' : '#ef4444' }}>{adjCoeff >= 0 ? '+' : ''}{adjCoeff.toFixed(2)} % pts</strong>
            {Math.abs(adjCoeff - rawCoeff) > 0.5
              ? ' — geography explains part of the gap.'
              : ' — geography is not a major confound.'}
          </div>
        )}
      </div>

      {/* Component comparison bar chart */}
      <div className="section-title">Score by component — Military vs. Civilian</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20, display: 'flex', gap: 16 }}>
        <span>Average score per TAF element. Higher is better.</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: '#60a5fa', display: 'inline-block' }} /> Civilian
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: '#fbbf24', display: 'inline-block' }} /> Military
        </span>
      </div>
      <ResponsiveContainer width="100%" height={360}>
        <BarChart data={barData} margin={{ top: 10, right: 20, bottom: 60, left: 0 }} barGap={2} barCategoryGap="30%">
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: 'var(--border)' }}
            angle={-25}
            textAnchor="end"
            interval={0}
          />
          <YAxis
            domain={civMilDomain}
            tickFormatter={v => `${v}%`}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<MilCompTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="Civilian" fill="#60a5fa" radius={[3, 3, 0, 0]} />
          <Bar dataKey="Military" fill="#fbbf24" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>

      {/* Effect sizes table */}
      <div style={{ marginTop: 40 }}>
        <div className="section-title">Effect sizes by component</div>
        <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 16 }}>
          Cohen's d = (civilian mean − military mean) / pooled SD. Positive = civilian is better.
          p-values from Welch's t-test (two-tailed).
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Component', 'Civilian avg', 'Military avg', 'Gap (% pts)', "Cohen's d", 'Effect', 'p-value'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Component' ? 'left' : 'right', padding: '6px 12px', color: 'var(--muted)', fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stats.map(s => (
                <tr key={s.key} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '7px 12px', color: 'var(--text)', fontWeight: s.key === 'overall_score' ? 600 : 400 }}>{s.label}</td>
                  <td style={{ padding: '7px 12px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{s.civMean.toFixed(1)}%</td>
                  <td style={{ padding: '7px 12px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{s.milMean.toFixed(1)}%</td>
                  <td style={{ padding: '7px 12px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: s.gap <= -0.5 ? '#22c55e' : s.gap >= 0.5 ? '#ef4444' : 'var(--text)', fontWeight: 600 }}>
                    {s.gap >= 0 ? '+' : ''}{s.gap.toFixed(1)}
                  </td>
                  <td style={{ padding: '7px 12px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: effectColor(s.d), fontWeight: 600 }}>
                    {s.d >= 0 ? '+' : ''}{s.d.toFixed(2)}
                  </td>
                  <td style={{ padding: '7px 12px', textAlign: 'right', color: effectColor(s.d) }}>{effectLabel(s.d)}</td>
                  <td style={{ padding: '7px 12px', textAlign: 'right', color: s.p < 0.05 ? 'var(--text)' : 'var(--muted)', fontStyle: s.p >= 0.05 ? 'italic' : 'normal' }}>
                    {fmtP(s.p)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
          Gap is civilian minus military — negative gap means military is better. p &lt; 0.05 indicates statistically significant difference.
        </div>
      </div>

      {/* OLS before/after region control */}
      {rawCoeff != null && adjCoeff != null && (
        <div style={{ marginTop: 40 }}>
          <div className="section-title">Military coefficient: raw vs. region-adjusted</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
            OLS coefficient on the military dummy before and after adding NOAA climate region controls.
            If the coefficient shrinks substantially after adjustment, geography explains part of the gap.
          </div>
          {[
            { label: 'Model 1: score ~ military', coeff: rawCoeff, note: 'No controls' },
            { label: 'Model 2: score ~ military + climate region', coeff: adjCoeff, note: 'Region-controlled' },
          ].map(({ label, coeff, note }) => {
            const maxAbs = Math.max(Math.abs(rawCoeff), Math.abs(adjCoeff), 0.1)
            const barW = Math.round((Math.abs(coeff) / maxAbs) * 120)
            const barColor = coeff >= 0 ? '#22c55e' : '#ef4444'
            return (
              <div key={label} style={{ marginBottom: 14, display: 'flex', alignItems: 'center', gap: 16 }}>
                <div style={{ width: 280, fontSize: 12, color: 'var(--muted)' }}>
                  <div style={{ color: 'var(--text)', fontWeight: 600, fontSize: 12 }}>{note}</div>
                  <div style={{ fontSize: 11 }}>{label}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ width: 130, height: 10, background: 'var(--surface2)', borderRadius: 4, overflow: 'hidden', direction: coeff < 0 ? 'rtl' : 'ltr' }}>
                    <div style={{ width: barW, height: '100%', background: barColor, borderRadius: 4 }} />
                  </div>
                  <span style={{ fontSize: 13, fontWeight: 700, color: barColor, minWidth: 60, fontVariantNumeric: 'tabular-nums' }}>
                    {coeff >= 0 ? '+' : ''}{coeff.toFixed(2)} % pts
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Score distribution comparison */}
      <div style={{ marginTop: 40 }}>
        <div className="section-title">Overall score distribution — Military vs. Civilian</div>
        <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20, display: 'flex', gap: 16 }}>
          <span>Count of airports in each 5-point score bucket.</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: '#60a5fa88', border: '1px solid #60a5fa', display: 'inline-block' }} /> Civilian
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: '#fbbf2488', border: '1px solid #fbbf24', display: 'inline-block' }} /> Military
          </span>
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={distData} margin={{ top: 10, right: 20, bottom: 30, left: 0 }} barGap={0} barCategoryGap="10%">
            <XAxis
              dataKey="label"
              tick={{ fill: 'var(--muted)', fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: 'var(--border)' }}
              interval={1}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fill: 'var(--muted)', fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              label={{ value: 'Airports', angle: -90, position: 'insideLeft', fill: 'var(--muted)', fontSize: 11 }}
            />
            <Tooltip content={<DistTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
            <Bar dataKey="civilian" name="Civilian" fill="#60a5fa" fillOpacity={0.7} radius={[2, 2, 0, 0]} />
            <Bar dataKey="military" name="Military" fill="#fbbf24" fillOpacity={0.8} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function Analytics({ onSelectAirport }) {
  const [airports,  setAirports]  = useState([])
  const [leadTime,  setLeadTime]  = useState([])
  const [daily,     setDaily]     = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [subTab,    setSubTab]    = useState('overview')

  useEffect(() => {
    Promise.all([fetchAnalytics(), fetchLeadTime(), fetchDailyComparisons()])
      .then(([ap, lt, dc]) => { setAirports(ap); setLeadTime(lt); setDaily(dc) })
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

  const TABS = [
    { id: 'overview',  label: 'Overview' },
    { id: 'military',  label: 'Military vs. Civilian' },
  ]

  return (
    <div>
      <div className="section-title" style={{ fontSize: 20, marginBottom: 4 }}>The real nerdy stuff</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        Data analytics across all {airports.length} tracked airports.
      </div>

      {/* Sub-tab navigation */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border)', marginBottom: 28 }}>
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setSubTab(id)}
            style={{
              padding: '8px 18px',
              border: 'none',
              background: 'transparent',
              color: subTab === id ? 'var(--text)' : 'var(--muted)',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: subTab === id ? 600 : 400,
              borderBottom: subTab === id ? '2px solid var(--accent, #60a5fa)' : '2px solid transparent',
              marginBottom: -1,
              borderRadius: '4px 4px 0 0',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {subTab === 'overview' && (
        <>
          <DailyComparisonsChart data={daily} />
          <RegionScoreChart airports={airports} />
          <ScoreHistogram airports={airports} />
          <ObsHistogram airports={airports} />
          <LeadTimeDecayChart data={leadTime} />
          <RegressionTable airports={airports} />
        </>
      )}

      {subTab === 'military' && (
        <MilitaryAnalysis airports={airports} />
      )}
    </div>
  )
}
