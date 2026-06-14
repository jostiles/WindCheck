export default function Welcome() {
  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '20px 24px' }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px', color: 'var(--muted)', marginBottom: 14 }}>
          What is this site about?
        </div>
        <p style={{ color: 'var(--muted)', lineHeight: 1.8 }}>
          This site grades Terminal Aerodrome Forecasts (TAFs) on how accurate they are by comparing them to hourly METAR observations. Browse the leaderboard to see which airports have the most — and least — accurate forecasts, or dig into the analytics for a deeper look at what drives forecast skill.
        </p>
      </div>
    </div>
  )
}
