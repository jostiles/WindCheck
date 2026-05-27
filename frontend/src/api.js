/**
 * api.js — thin wrappers around the FastAPI backend.
 * All functions return parsed JSON or throw an Error with a human message.
 *
 * In development the Vite proxy forwards bare paths to localhost:8000.
 * In production set VITE_API_URL to the Fly.io backend URL (no trailing slash).
 */

const API_BASE = import.meta.env.VITE_API_URL ?? ''

async function _get(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let msg = `HTTP ${res.status}`
    try { msg = JSON.parse(text).detail ?? msg } catch (_) {}
    throw new Error(msg)
  }
  return res.json()
}

export const fetchAirport   = (icao) => _get(`/airport/${icao.toUpperCase()}`)
export const fetchSnapshot  = (icao) => _get(`/airport/${icao.toUpperCase()}/snapshot`)
export const fetchByHour   = (icao, maxHour = 24) =>
  _get(`/airport/${icao.toUpperCase()}/by-hour?max_hour=${maxHour}`)
export const fetchRecent   = (icao, limit = 48) =>
  _get(`/airport/${icao.toUpperCase()}/recent?limit=${limit}`)
export const fetchMapData     = (minObs = 1) => _get(`/map-data?min_obs=${minObs}`)
export const fetchLeaderboard = (sortBy = 'overall_score', minObs = 1) =>
  _get(`/leaderboard?sort_by=${sortBy}&min_obs=${minObs}&limit=500`)

export async function triggerIngest(icao) {
  const res = await fetch(`${API_BASE}/ingest/${icao.toUpperCase()}`, { method: 'POST' })
  if (!res.ok) throw new Error(`Ingest failed: HTTP ${res.status}`)
  return res.json()
}
