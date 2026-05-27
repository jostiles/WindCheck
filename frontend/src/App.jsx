import { useState, useEffect, useCallback, useRef } from 'react'
import './index.css'
import { fetchAirport, fetchByHour, fetchRecent, triggerIngest } from './api'
import MetricsGrid         from './components/MetricsGrid'
import AccuracyChart       from './components/AccuracyChart'
import RecentTable         from './components/RecentTable'
import Leaderboard         from './components/Leaderboard'
import About               from './components/About'
import SnapshotComparison  from './components/SnapshotComparison'
import MapView             from './components/MapView'

// ── Zulu clock ───────────────────────────────────────────────────────────────

function ZuluClock() {
  const [time, setTime] = useState('')

  useEffect(() => {
    function tick() {
      const now = new Date()
      const hh = String(now.getUTCHours()).padStart(2, '0')
      const mm = String(now.getUTCMinutes()).padStart(2, '0')
      const ss = String(now.getUTCSeconds()).padStart(2, '0')
      setTime(`${hh}:${mm}:${ss}Z`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div style={{ fontFamily: 'monospace', fontSize: 13, color: 'var(--muted)', letterSpacing: '0.5px', whiteSpace: 'nowrap' }}>
      {time}
    </div>
  )
}

// ── Airport detail view ───────────────────────────────────────────────────

function AirportView({ icao, onClose }) {
  const [airport,  setAirport]  = useState(null)
  const [byHour,   setByHour]   = useState([])
  const [recent,   setRecent]   = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [ingesting, setIngesting] = useState(false)
  const [ingestMsg, setIngestMsg] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      fetchAirport(icao),
      fetchByHour(icao).catch(() => []),
      fetchRecent(icao, 48).catch(() => []),
    ])
      .then(([ap, bh, rec]) => {
        setAirport(ap)
        setByHour(bh)
        setRecent(rec)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [icao])

  useEffect(() => { load() }, [load])

  async function handleIngest() {
    setIngesting(true)
    setIngestMsg(null)
    try {
      const res = await triggerIngest(icao)
      setIngestMsg(res.status === 'queued' ? 'Ingest queued — refresh in ~30 s' : 'Already running')
    } catch (e) {
      setIngestMsg(`Error: ${e.message}`)
    } finally {
      setIngesting(false)
    }
  }

  if (loading) return (
    <div className="state-box" style={{ paddingTop: 80 }}>
      <div className="spinner" />
    </div>
  )

  if (error) return (
    <div>
      <div className="error-banner">Could not load {icao}: {error}</div>
      <button className="btn btn-ghost btn-sm" onClick={onClose}>← Back</button>
    </div>
  )

  const { name, lat, lon, summary } = airport

  return (
    <div>
      {/* Airport header */}
      <div className="airport-header">
        <button
          className="btn btn-ghost btn-sm"
          style={{ alignSelf: 'center' }}
          onClick={onClose}
        >
          ←
        </button>
        <div className="airport-icao">{icao}</div>
        {name && <div className="airport-name">{name.trim()}</div>}
        <div className="airport-actions">
          {ingestMsg && <span className="ingest-badge">{ingestMsg}</span>}
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleIngest}
            disabled={ingesting}
          >
            {ingesting ? '…' : '↻ Refresh data'}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={load}>
            ↺ Reload
          </button>
        </div>
      </div>

      {/* Current snapshot comparison */}
      <SnapshotComparison icao={icao} />

      {/* Per-parameter score cards */}
      <div className="section-title">Accuracy summary</div>
      <MetricsGrid summary={summary} />

      {/* By-hour accuracy chart */}
      <div className="section-title">Accuracy by forecast-hour offset</div>
      {byHour.length > 0
        ? <AccuracyChart data={byHour} />
        : <div className="state-box" style={{ padding: '32px 24px' }}>
            <p>Not enough data to show hourly breakdown yet.</p>
            <p className="state-hint">The pipeline needs multiple runs to populate multiple hour buckets.</p>
          </div>
      }

      {/* Recent observations table */}
      <RecentTable rows={recent} />
    </div>
  )
}

// ── App shell ─────────────────────────────────────────────────────────────

const MAX_AIRPORT_TABS = 6

export default function App() {
  const [tab,            setTab]            = useState('leaderboard')
  const [query,          setQuery]          = useState('')
  const [selected,       setSelected]       = useState(null)       // active airport ICAO
  const [recentAirports, setRecentAirports] = useState([])         // up to 6, most-recent first

  function openAirport(icao) {
    setRecentAirports(prev => {
      const filtered = prev.filter(c => c !== icao)
      return [icao, ...filtered].slice(0, MAX_AIRPORT_TABS)
    })
    setSelected(icao)
    setQuery(icao)
    setTab('airport')
  }

  function closeAirport(icao, e) {
    e.stopPropagation()
    setRecentAirports(prev => {
      const next = prev.filter(c => c !== icao)
      if (icao === selected) {
        if (next.length > 0) {
          setSelected(next[0])
          setTab('airport')
        } else {
          setSelected(null)
          setTab('leaderboard')
        }
      }
      return next
    })
  }

  function search(e) {
    e.preventDefault()
    const icao = query.trim().toUpperCase()
    if (icao.length !== 4) return
    openAirport(icao)
  }

  function backToLeaderboard() {
    setTab('leaderboard')
    setSelected(null)
  }

  function selectFromMap(icao) { openAirport(icao) }
  function selectAirport(icao)  { openAirport(icao) }

  return (
    <>
      {/* ── Header ── */}
      <header className="app-header">
        <div className="app-logo" style={{ cursor: 'pointer' }} onClick={backToLeaderboard}>
          Wind<span>Check</span>
        </div>

        <ZuluClock />

        <form className="search-form" onSubmit={search} style={{ marginLeft: 'auto' }}>
          <input
            className="search-input"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="ICAO code…"
            maxLength={4}
            spellCheck={false}
          />
          <button
            className="btn btn-primary"
            type="submit"
            disabled={query.trim().length !== 4}
          >
            Search
          </button>
        </form>
      </header>

      {/* ── Tabs ── */}
      <nav className="tabs">
        <button
          className={`tab ${tab === 'leaderboard' ? 'active' : ''}`}
          onClick={backToLeaderboard}
        >
          Leaderboard
        </button>
        <button
          className={`tab ${tab === 'map' ? 'active' : ''}`}
          onClick={() => setTab('map')}
        >
          Map
        </button>
        {recentAirports.map(icao => (
          <button
            key={icao}
            className={`tab ${tab === 'airport' && selected === icao ? 'active' : ''}`}
            onClick={() => { setSelected(icao); setTab('airport') }}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            {icao}
            <span
              onClick={e => closeAirport(icao, e)}
              style={{ fontSize: 11, lineHeight: 1, opacity: 0.5, marginLeft: 2 }}
              onMouseEnter={e => e.currentTarget.style.opacity = 1}
              onMouseLeave={e => e.currentTarget.style.opacity = 0.5}
            >
              ×
            </span>
          </button>
        ))}
        <button
          className={`tab ${tab === 'about' ? 'active' : ''}`}
          onClick={() => setTab('about')}
          style={{ marginLeft: 'auto' }}
        >
          How it's graded
        </button>
      </nav>

      {/* ── Content ── */}
      <main className="main-content">
        {tab === 'about'
          ? <About />
          : tab === 'map'
            ? <MapView onSelectAirport={selectFromMap} />
            : tab === 'airport' && selected
              ? <AirportView key={selected} icao={selected} onClose={backToLeaderboard} />
              : <Leaderboard onSelectAirport={selectAirport} />
        }

      </main>
    </>
  )
}
