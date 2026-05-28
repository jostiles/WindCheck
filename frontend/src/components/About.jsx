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
          or overcast cloud layer) and visibility. These categories are used directly
          in the ceiling altitude and visibility scoring — a forecast that lands in the
          same category as the observation is treated as operationally correct even if
          the raw numbers differ slightly.
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

          <ScoreRow color="#0ea5e9" label="Sky Coverage" score="0.0 – 1.0">
            <p style={{ color: 'var(--muted)', lineHeight: 1.6, fontSize: 13, marginBottom: 8 }}>
              Coverage types are assigned a rank on an ordered scale from clear to fully obscured.
              The score is a linear function of the rank difference — adjacent types receive partial
              credit rather than a binary hit or miss.
            </p>
            <table style={{ fontSize: 12, borderCollapse: 'collapse', marginBottom: 8, width: '100%' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Coverage', 'Rank', '', 'Coverage', 'Rank'].map((h, i) => (
                    <th key={i} style={{ textAlign: 'left', padding: '4px 10px', color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', fontSize: 10 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr><td style={tdS}>SKC / CLR</td><td style={tdS}>0</td><td style={tdS} /><td style={tdS}>BKN</td><td style={tdS}>3</td></tr>
                <tr><td style={tdS}>FEW</td><td style={tdS}>1</td><td style={tdS} /><td style={tdS}>OVC / VV</td><td style={tdS}>4</td></tr>
                <tr><td style={tdS}>SCT</td><td style={tdS}>2</td><td style={tdS} /><td style={tdS}></td><td style={tdS}></td></tr>
              </tbody>
            </table>
            <Formula>score = 1 − |forecast_rank − observed_rank| / 4</Formula>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 6 }}>
              Examples: BKN vs BKN → 1.00 · BKN vs OVC → 0.75 · SCT vs OVC → 0.50 · FEW vs OVC → 0.25 · SKC vs OVC → 0.00
            </p>
          </ScoreRow>

          <ScoreRow color="#38bdf8" label="Ceiling Altitude" score="0.0 – 1.0">
            <p style={{ color: 'var(--muted)', lineHeight: 1.6, fontSize: 13, marginBottom: 8 }}>
              Rather than comparing raw altitude numbers, each ceiling is mapped to an FAA flight-category
              tier. The score reflects how far apart the tiers are. A reported ceiling of "none" (clear sky)
              is treated as VFR (tier 3).
            </p>
            <table style={{ fontSize: 12, borderCollapse: 'collapse', marginBottom: 8 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Tier', 'Category', 'Ceiling'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '4px 10px', color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', fontSize: 10 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr><td style={tdS}>3</td><td style={tdS}>VFR</td><td style={tdS}>≥ 3,000 ft (or no ceiling)</td></tr>
                <tr><td style={tdS}>2</td><td style={tdS}>MVFR</td><td style={tdS}>1,000 – 2,999 ft</td></tr>
                <tr><td style={tdS}>1</td><td style={tdS}>IFR</td><td style={tdS}>500 – 999 ft</td></tr>
                <tr><td style={tdS}>0</td><td style={tdS}>LIFR</td><td style={tdS}>{'< 500 ft'}</td></tr>
              </tbody>
            </table>
            <Formula>score = max(0, 1 − |forecast_tier − observed_tier| / 3)</Formula>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 6 }}>
              Same tier → 1.00 · 1 tier apart → 0.67 · 2 tiers apart → 0.33 · 3 tiers apart → 0.00
            </p>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 4 }}>
              Rationale: a ceiling of 900 ft vs 1,100 ft is an operationally trivial difference (both IFR);
              a ceiling of 900 ft vs "no ceiling" is not. The tier system captures what actually matters to
              a pilot rather than penalising every 100 ft of altitude error equally.
            </p>
          </ScoreRow>

          <ScoreRow color="#f59e0b" label="Visibility" score="0.0 – 1.0">
            <p style={{ color: 'var(--muted)', lineHeight: 1.6, fontSize: 13, marginBottom: 8 }}>
              Visibility is scored using the same FAA flight-category tier system as ceiling altitude.
              Each visibility value is mapped to a tier, and the score reflects the tier distance.
            </p>
            <table style={{ fontSize: 12, borderCollapse: 'collapse', marginBottom: 8 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Tier', 'Category', 'Visibility'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '4px 10px', color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', fontSize: 10 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr><td style={tdS}>3</td><td style={tdS}>VFR</td><td style={tdS}>≥ 5 SM</td></tr>
                <tr><td style={tdS}>2</td><td style={tdS}>MVFR</td><td style={tdS}>3 – 4.99 SM</td></tr>
                <tr><td style={tdS}>1</td><td style={tdS}>IFR</td><td style={tdS}>1 – 2.99 SM</td></tr>
                <tr><td style={tdS}>0</td><td style={tdS}>LIFR</td><td style={tdS}>{'< 1 SM'}</td></tr>
              </tbody>
            </table>
            <Formula>score = max(0, 1 − |forecast_tier − observed_tier| / 3)</Formula>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 6 }}>
              P6SM forecasts ("greater than 6 SM") are assigned VFR tier 3, since the forecast is a lower
              bound rather than an exact value — any observed visibility ≥ 5 SM scores a perfect tier match.
            </p>
          </ScoreRow>

          <ScoreRow color="#10b981" label="Wind Speed" score="0.0 – 1.0">
            <p style={{ color: 'var(--muted)', lineHeight: 1.6, fontSize: 13, marginBottom: 8 }}>
              Wind speed is scored using percentage-based error on the peak wind magnitude for each side.
              When a gust is reported, the gust becomes the peak — because the gust, not the sustained
              speed, is what challenges pilots and aircraft systems.
            </p>
            <Formula>peak_wind = max(speed, gust)  ← when a gust is reported; else speed alone</Formula>
            <Formula>error = |forecast_peak − observed_peak| / max(forecast_peak, observed_peak, 1)</Formula>
            <Formula>score = max(0, 1 − error)</Formula>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 6 }}>
              The percentage denominator means absolute errors are judged in context: a 10 kt miss on a
              10 kt forecast (100% error → score ≈ 0.00) is penalised far more than a 10 kt miss on a
              50 kt forecast (20% error → score ≈ 0.80). The floor of 1 kt in the denominator prevents
              division by zero on calm-wind observations.
            </p>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 4 }}>
              Examples: forecast 10 G 18 kt vs observed 12 G 20 kt → peaks 18 vs 20, error = 2/20 = 10%, score = 0.90 ·
              forecast 8 kt vs observed 20 kt → error = 12/20 = 60%, score = 0.40
            </p>
          </ScoreRow>

          <ScoreRow color="#f43f5e" label="Wind Direction" score="0.0 – 1.0">
            <p style={{ color: 'var(--muted)', lineHeight: 1.6, fontSize: 13, marginBottom: 8 }}>
              Wind direction is scored with a continuous linear decay from perfect agreement to zero at 90°.
              Circular arithmetic is used so that the shortest angular path is always taken — 350° vs 010° is
              a 20° difference, not 340°.
            </p>
            <Formula>diff = min(|forecast° − observed°|, 360 − |forecast° − observed°|)  ← range 0–180°</Formula>
            <Formula>score = max(0, 1 − diff / 90)</Formula>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 6 }}>
              Score examples: 0° off → 1.00 · 30° off → 0.67 · 45° off → 0.50 · 60° off → 0.33 · 90°+ off → 0.00
            </p>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 4 }}>
              The 90° zero-point reflects that a right-angle wind error represents a fundamentally wrong
              forecast — a pilot computing crosswind components would be pointing the wrong direction entirely.
              Variable winds (VRB) on either side are excluded from scoring since there is no meaningful
              direction to compare.
            </p>
          </ScoreRow>

          <ScoreRow color="#a78bfa" label="Weather Phenomena" score="Weighted F1">
            <p style={{ color: 'var(--muted)', lineHeight: 1.6, fontSize: 13, marginBottom: 8 }}>
              Tracked weather phenomena (TS, RA, SN, FG, etc.) are scored using a severity-weighted F1 score.
              Each phenomenon is assigned a hazard weight — missing a thunderstorm costs far more than missing
              light mist.
            </p>
            <table style={{ fontSize: 12, borderCollapse: 'collapse', marginBottom: 8, width: '100%' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Weight', 'Phenomena', 'Rationale'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '4px 10px', color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', fontSize: 10 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr><td style={tdS}>5.0</td><td style={tdS}>TS, TSRA, TSSN, TSGR, …</td><td style={tdS}>Flight-safety critical</td></tr>
                <tr><td style={tdS}>4.0</td><td style={tdS}>FZRA, FZDZ, FZSN</td><td style={tdS}>Icing hazard</td></tr>
                <tr><td style={tdS}>3.0</td><td style={tdS}>BLSN, DRSN</td><td style={tdS}>Structural / visibility</td></tr>
                <tr><td style={tdS}>2.0</td><td style={tdS}>SN, PL, RA, FG</td><td style={tdS}>Significant ops impact</td></tr>
                <tr><td style={tdS}>1.0</td><td style={tdS}>DZ, GR, GS</td><td style={tdS}>Minor impact</td></tr>
                <tr><td style={tdS}>0.5</td><td style={tdS}>BR, HZ, FU, SA, DU</td><td style={tdS}>Low impact</td></tr>
              </tbody>
            </table>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginBottom: 4 }}>
              For each observation, phenomena are classified as:
            </p>
            <ul style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.8, paddingLeft: 20, marginBottom: 8 }}>
              <li><strong style={{ color: 'var(--text)' }}>TP</strong> (true positive) — forecast and observed</li>
              <li><strong style={{ color: 'var(--text)' }}>FP</strong> (false positive) — forecast but not observed (false alarm)</li>
              <li><strong style={{ color: 'var(--text)' }}>FN</strong> (false negative) — observed but not forecast (miss)</li>
            </ul>
            <Formula>weighted precision = Σ weight(TP) / (Σ weight(TP) + Σ weight(FP))</Formula>
            <Formula>weighted recall    = Σ weight(TP) / (Σ weight(TP) + Σ weight(FN))</Formula>
            <Formula>F1 = 2 × precision × recall / (precision + recall)</Formula>
            <p style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.6, marginTop: 6 }}>
              The F1 score is the harmonic mean of precision and recall — it is low if either is low,
              so a forecast must both avoid false alarms and catch what actually happened.
              When only one side has weather, the available metric (precision or recall) is used alone in
              the overall score.
            </p>
          </ScoreRow>

        </div>
      </Section>

      {/* ── Overall Score ── */}
      <Section title="Overall Score">
        <p style={{ color: 'var(--muted)', lineHeight: 1.7, marginBottom: 12 }}>
          The overall score is the unweighted mean of all non-null parameter scores
          for a given observation. All six parameters now produce continuous scores in the
          range 0.0 – 1.0, so no parameter dominates simply by producing large binary swings.
          A parameter is excluded (null) when there is no observation value to compare
          against — for example, wind direction is excluded when winds are variable on one
          side but not the other.
        </p>
        <p style={{ color: 'var(--muted)', lineHeight: 1.7, marginBottom: 12 }}>
          On the leaderboard, each airport's displayed score is the mean overall score across
          all of its stored observations (minimum observation count selectable via the filter).
          The weight sliders let you compute a custom weighted mean of the five parameter
          scores client-side without re-querying the server.
        </p>
        <ScoreBand color="#22c55e" range="≥ 80%" label="Good" desc="Forecast closely matched conditions across all parameters" />
        <ScoreBand color="#f59e0b" range="60 – 79%" label="Fair" desc="Mostly correct, with meaningful misses on some parameters" />
        <ScoreBand color="#ef4444" range="< 60%" label="Poor" desc="Significant forecast errors across one or more parameters" />
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
          (no key required). The pipeline runs hourly on a cloud server, storing results in a
          SQLite database. Each airport accumulates ~24 scored observations per day.
        </p>
      </Section>
    </div>
  )
}

// ── Shared cell style ─────────────────────────────────────────────────────
const tdS = { padding: '5px 10px', color: 'var(--muted)', borderBottom: '1px solid var(--border)' }

// ── Sub-components ────────────────────────────────────────────────────────

function Formula({ children }) {
  return (
    <div style={{
      fontFamily: 'monospace',
      fontSize: 12,
      background: 'var(--surface2)',
      border: '1px solid var(--border)',
      borderRadius: 6,
      padding: '7px 12px',
      margin: '6px 0',
      color: 'var(--accent2)',
      letterSpacing: '0.2px',
    }}>
      {children}
    </div>
  )
}

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

function ScoreRow({ color, label, score, children }) {
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <div style={{ width: 4, borderRadius: 4, background: color, flexShrink: 0, alignSelf: 'stretch', minHeight: 40 }} />
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 }}>
          <span style={{ fontWeight: 700, color: 'var(--text)' }}>{label}</span>
          <span style={{ fontSize: 11, color: color, fontWeight: 600, background: `${color}22`, padding: '1px 7px', borderRadius: 4 }}>{score}</span>
        </div>
        {children}
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
