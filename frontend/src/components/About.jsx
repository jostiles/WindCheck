export default function About() {
  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: 'var(--accent2)', letterSpacing: -0.5, marginBottom: 6 }}>
          About Wind Check
        </h1>
        <p style={{ color: 'var(--muted)', lineHeight: 1.7, marginBottom: 12 }}>
          Welcome to my AI-slop created website that grades airports' TAFs on how accurate they are.
          The overall gist of it is grade predicted TAFs against what is currently happening on the METAR.
          This is not for official grading of any weather shop.
        </p>
        <p style={{ color: 'var(--muted)', lineHeight: 1.7 }}>
          Data is fetched from <a href="https://aviationweather.gov" target="_blank" rel="noreferrer" style={{ color: 'var(--accent2)' }}>aviationweather.gov</a>,
          each hourly METAR observation is aligned to the correct TAF forecast period,
          and the forecast is scored across the parameters below.
        </p>
      </div>

      {/* ── Flight Categories ── */}
      <Section title="Flight Categories">
        <p style={{ color: 'var(--muted)', marginBottom: 16, lineHeight: 1.7 }}>
          The FAA defines four flight categories based on ceiling (lowest broken
          or overcast cloud layer) and visibility. Wind Check scores ceiling
          accuracy as a category match — a forecast that nails the exact
          altitude but misses the category counts as wrong.
        </p>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Category', 'Ceiling', 'Visibility', 'Meaning'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 12px', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--muted)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <CatRow badge="VFR"  badgeCls="fc-VFR"  ceil="≥ 3,000 ft AGL" vis="≥ 5 SM"      meaning="Visual Flight Rules — clear conditions" />
            <CatRow badge="MVFR" badgeCls="fc-MVFR" ceil="1,000 – 2,999 ft" vis="3 – 4 SM"   meaning="Marginal VFR — usable but degraded" />
            <CatRow badge="IFR"  badgeCls="fc-IFR"  ceil="500 – 999 ft"   vis="1 – 2 SM"   meaning="Instrument Flight Rules — low visibility" />
            <CatRow badge="LIFR" badgeCls="fc-LIFR" ceil="< 500 ft"        vis="< 1 SM"     meaning="Low IFR — severe, often near-zero visibility" />
          </tbody>
        </table>
        <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 10 }}>
          Either condition (ceiling <em>or</em> visibility) triggers the lower category — whichever is worse governs.
        </p>
      </Section>

      {/* ── Scoring Parameters ── */}
      <Section title="How Each Parameter Is Scored">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ScoreRow
            color="#0ea5e9"
            label="Sky Coverage"
            score="0 or 1"
            description="Compares the coverage type of the lowest ceiling layer (BKN, OVC, VV) between forecast and observed. Full credit if both agree on the coverage type — including both reporting no ceiling (clear). No credit if one side has a ceiling layer and the other doesn't, or if the types differ (e.g. BKN vs OVC)."
          />
          <ScoreRow
            color="#38bdf8"
            label="Ceiling Altitude"
            score="0 or 1"
            description="Compares the altitude of the lowest ceiling layer in feet AGL. Full credit if the forecast ceiling height is within ±500 ft of the observed ceiling. No credit if the difference exceeds 500 ft. Excluded (null) when either the forecast or the observation reports no ceiling."
          />
          <ScoreRow
            color="#f59e0b"
            label="Visibility"
            score="0 or 1"
            description="Full credit if the forecast visibility is within ±1 statute mile of the observed visibility. P6SM ('greater than 6 SM') forecasts are scored one-sided: any observed value ≥ 6 SM counts as a hit, since the forecast is a lower bound, not an exact value."
          />
          <ScoreRow
            color="#10b981"
            label="Wind Speed"
            score="0 or 1"
            description="Full credit if the forecast wind speed is within ±5 knots of the observed speed. Calm wind (0 kt) is a valid value on both sides."
          />
          <ScoreRow
            color="#f43f5e"
            label="Wind Direction"
            score="0 or 1"
            description="Full credit if the angular difference between forecast and observed direction is ≤ 30°, using circular arithmetic (so 350° vs 010° = 20°, not 340°). Variable winds (VRB) on either side are excluded from scoring."
          />
          <ScoreRow
            color="#a78bfa"
            label="Weather Phenomena"
            score="Precision + Recall"
            description="Tracks significant weather codes: TS, RA, SN, DZ, FG, GR, and others. Precision = what fraction of forecast phenomena actually occurred. Recall = what fraction of observed phenomena were forecast. Both are averaged into an F1-style score for the overall."
          />
        </div>
      </Section>

      {/* ── Overall Score ── */}
      <Section title="Overall Score">
        <p style={{ color: 'var(--muted)', lineHeight: 1.7 }}>
          The overall score is the unweighted mean of all non-null parameter scores
          for a given observation. A parameter is excluded (null) when neither the
          forecast nor the observation provided a value — for example, wind direction
          is excluded when wind speed is calm on both sides.
        </p>
        <ScoreBand color="#22c55e" range="≥ 80%" label="Good" desc="Forecast closely matched conditions" />
        <ScoreBand color="#f59e0b" range="60 – 79%" label="Fair" desc="Mostly correct, some parameter misses" />
        <ScoreBand color="#ef4444" range="< 60%" label="Poor" desc="Significant forecast errors" />
      </Section>

      {/* ── TAF Alignment ── */}
      <Section title="TAF Period Alignment">
        <p style={{ color: 'var(--muted)', lineHeight: 1.7, marginBottom: 12 }}>
          TAFs contain multiple period groups that override conditions at different times.
          Wind Check resolves the correct forecast for each METAR using this priority:
        </p>
        <ol style={{ color: 'var(--muted)', paddingLeft: 20, lineHeight: 2 }}>
          <li><strong style={{ color: 'var(--text)' }}>FM (From)</strong> — completely replaces all conditions from its start time. The last FM before the observation time wins.</li>
          <li><strong style={{ color: 'var(--text)' }}>BECMG (Becoming)</strong> — if the transition window has closed before the observation, the new BECMG conditions are merged into the base. If still in progress, the pre-BECMG conditions are used.</li>
          <li><strong style={{ color: 'var(--text)' }}>TEMPO / PROB</strong> — temporary overlays recorded separately. Observations are always scored against the base (FM/BECMG) forecast, not the TEMPO, since TEMPOs are intermittent by definition.</li>
        </ol>
      </Section>

      {/* ── Data Source ── */}
      <Section title="Data Source">
        <p style={{ color: 'var(--muted)', lineHeight: 1.7 }}>
          All TAF and METAR data is fetched from the{' '}
          <a href="https://aviationweather.gov/api/data/" target="_blank" rel="noreferrer" style={{ color: 'var(--accent2)' }}>
            Aviation Weather Center ADDS API
          </a>{' '}
          (no key required). The pipeline runs hourly, storing results in a local
          SQLite database. Each airport accumulates ~24 scored observations per day.
        </p>
      </Section>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '20px 24px', marginBottom: 20 }}>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px', color: 'var(--muted)', marginBottom: 14 }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function CatRow({ badge, badgeCls, ceil, vis, meaning }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td style={{ padding: '10px 12px' }}>
        <span className={`fc-badge ${badgeCls}`}>{badge}</span>
      </td>
      <td style={{ padding: '10px 12px', color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>{ceil}</td>
      <td style={{ padding: '10px 12px', color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>{vis}</td>
      <td style={{ padding: '10px 12px', color: 'var(--muted)' }}>{meaning}</td>
    </tr>
  )
}

function ScoreRow({ color, label, score, description }) {
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <div style={{ width: 4, borderRadius: 4, background: color, flexShrink: 0, alignSelf: 'stretch', minHeight: 40 }} />
      <div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <span style={{ fontWeight: 700, color: 'var(--text)' }}>{label}</span>
          <span style={{ fontSize: 11, color: color, fontWeight: 600, background: `${color}22`, padding: '1px 7px', borderRadius: 4 }}>{score}</span>
        </div>
        <p style={{ color: 'var(--muted)', lineHeight: 1.6, fontSize: 13 }}>{description}</p>
      </div>
    </div>
  )
}

function ScoreBand({ color, range, label, desc }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 12 }}>
      <div style={{ width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0 }} />
      <span style={{ fontWeight: 700, color, minWidth: 70 }}>{range}</span>
      <span style={{ fontWeight: 600, color: 'var(--text)', minWidth: 50 }}>{label}</span>
      <span style={{ color: 'var(--muted)', fontSize: 13 }}>{desc}</span>
    </div>
  )
}
