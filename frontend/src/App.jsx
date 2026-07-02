import { useState, useEffect, useCallback } from 'react'

const API = ''  // same origin when served by FastAPI

// ── Status badge color map ──────────────────────────────────────────────────
const STATUS_STYLES = {
  pending:      'bg-gray-600 text-gray-100',
  generating:   'bg-blue-600 text-blue-100',
  uploading:    'bg-yellow-500 text-yellow-100',
  published:    'bg-green-600 text-green-100',
  failed:       'bg-red-600 text-red-100',
  upload_failed:'bg-orange-500 text-orange-100',
}

function StatusBadge({ status }) {
  const cls = STATUS_STYLES[status] ?? 'bg-gray-500 text-white'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold uppercase ${cls}`}>
      {status}
    </span>
  )
}

// ── Stat Card ───────────────────────────────────────────────────────────────
function StatCard({ label, value, color = 'text-white' }) {
  return (
    <div className="bg-slate-800 rounded-xl p-5 flex flex-col gap-1 shadow">
      <span className="text-slate-400 text-sm">{label}</span>
      <span className={`text-3xl font-bold ${color}`}>{value ?? '—'}</span>
    </div>
  )
}

// ── Bar Chart (7-day) ────────────────────────────────────────────────────────
function BarChart({ days }) {
  if (!days || days.length === 0) {
    return <p className="text-slate-500 text-sm">No data yet.</p>
  }

  const sorted = [...days].sort((a, b) => a.stat_date.localeCompare(b.stat_date))
  const maxVal = Math.max(...sorted.map(d => (d.generated || 0) + (d.failed || 0)), 1)

  return (
    <div className="flex items-end gap-3 h-32">
      {sorted.map(d => {
        const gen   = d.generated  || 0
        const pub   = d.published  || 0
        const fail  = d.failed     || 0
        const total = gen + fail
        const pctGen  = (gen  / maxVal) * 100
        const pctPub  = (pub  / maxVal) * 100
        const pctFail = (fail / maxVal) * 100
        const label = d.stat_date.slice(5)   // MM-DD
        return (
          <div key={d.stat_date} className="flex flex-col items-center gap-1 flex-1">
            <div className="w-full flex flex-col-reverse" style={{ height: '96px' }}>
              <div
                title={`Failed: ${fail}`}
                style={{ height: `${pctFail}%` }}
                className="w-full bg-red-500 rounded-sm"
              />
              <div
                title={`Generated: ${gen}`}
                style={{ height: `${pctGen}%` }}
                className="w-full bg-blue-500 rounded-sm"
              />
            </div>
            <span className="text-xs text-slate-400">{label}</span>
          </div>
        )
      })}
      <div className="flex flex-col gap-1 text-xs text-slate-400 ml-2">
        <span><span className="inline-block w-2 h-2 bg-blue-500 mr-1 rounded-sm"/>Gen</span>
        <span><span className="inline-block w-2 h-2 bg-red-500 mr-1 rounded-sm"/>Fail</span>
      </div>
    </div>
  )
}

// ── Daily Limit Progress ─────────────────────────────────────────────────────
function DailyLimit({ used, limit }) {
  const pct = limit > 0 ? Math.round((used / limit) * 100) : 0
  const color = pct >= 100 ? 'bg-red-500' : pct >= 66 ? 'bg-yellow-400' : 'bg-green-500'
  return (
    <div className="bg-slate-800 rounded-xl p-5 shadow">
      <div className="flex justify-between mb-2">
        <span className="text-slate-400 text-sm">Daily Limit</span>
        <span className="text-white font-semibold text-sm">{used}/{limit} used</span>
      </div>
      <div className="w-full bg-slate-700 rounded-full h-3">
        <div className={`${color} h-3 rounded-full transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <p className="text-slate-500 text-xs mt-1">{limit - used} remaining today</p>
    </div>
  )
}

// ── API Request Log ──────────────────────────────────────────────────────────
function RequestLog({ requests }) {
  if (!requests || requests.length === 0) {
    return <p className="text-slate-500 text-sm">No API calls yet.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-400 border-b border-slate-700">
            <th className="pb-2 text-left">Service</th>
            <th className="pb-2 text-left">Endpoint</th>
            <th className="pb-2 text-left">Status</th>
            <th className="pb-2 text-left">Latency</th>
            <th className="pb-2 text-left">Time</th>
          </tr>
        </thead>
        <tbody>
          {requests.map(r => (
            <tr key={r.id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
              <td className="py-1.5 pr-3 font-mono text-blue-400">{r.service}</td>
              <td className="py-1.5 pr-3 text-slate-300">{r.endpoint}</td>
              <td className="py-1.5 pr-3">
                <span className={r.success ? 'text-green-400' : 'text-red-400'}>
                  {r.status_code}
                </span>
              </td>
              <td className="py-1.5 pr-3 text-slate-400">{r.latency_ms ? `${r.latency_ms}ms` : '—'}</td>
              <td className="py-1.5 text-slate-500">{r.created_at?.slice(11, 19)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Podcast Table ────────────────────────────────────────────────────────────
function PodcastTable({ podcasts }) {
  if (!podcasts || podcasts.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">
        <p className="text-4xl mb-2">🎙️</p>
        <p>No episodes yet. Click "Run Now" to generate your first one!</p>
      </div>
    )
  }

  const fmtDate = s => s ? s.slice(0, 16).replace('T', ' ') : '—'
  const fmtDur  = s => s ? `${Math.floor(s / 60)}m ${s % 60}s` : '—'

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-400 border-b border-slate-700 text-left">
            <th className="pb-3 pr-4">Topic</th>
            <th className="pb-3 pr-4">Category</th>
            <th className="pb-3 pr-4">Status</th>
            <th className="pb-3 pr-4">Created</th>
            <th className="pb-3 pr-4">Published</th>
            <th className="pb-3 pr-4">Duration</th>
            <th className="pb-3">Links</th>
          </tr>
        </thead>
        <tbody>
          {podcasts.map(p => (
            <tr key={p.id} className="border-b border-slate-700/50 hover:bg-slate-700/20">
              <td className="py-3 pr-4">
                <div className="max-w-xs">
                  <p className="text-white font-medium line-clamp-2 leading-snug">
                    {p.title || p.topic}
                  </p>
                  {p.title && p.title !== p.topic && (
                    <p className="text-slate-500 text-xs mt-0.5 line-clamp-1">{p.topic}</p>
                  )}
                </div>
              </td>
              <td className="py-3 pr-4 text-slate-400 text-xs whitespace-nowrap">{p.category || '—'}</td>
              <td className="py-3 pr-4"><StatusBadge status={p.status} /></td>
              <td className="py-3 pr-4 text-slate-400 text-xs whitespace-nowrap">{fmtDate(p.created_at)}</td>
              <td className="py-3 pr-4 text-slate-400 text-xs whitespace-nowrap">{fmtDate(p.published_at)}</td>
              <td className="py-3 pr-4 text-slate-400 text-xs">{fmtDur(p.duration_sec)}</td>
              <td className="py-3 text-xs flex gap-2 items-center">
                {p.spotify_url && (
                  <a href={p.spotify_url} target="_blank" rel="noreferrer"
                     className="text-green-400 hover:text-green-300 underline">Spotify</a>
                )}
                {p.apple_url && (
                  <a href={p.apple_url} target="_blank" rel="noreferrer"
                     className="text-purple-400 hover:text-purple-300 underline">Apple</a>
                )}
                {!p.spotify_url && !p.apple_url && <span className="text-slate-600">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [stats, setStats]       = useState(null)
  const [podcasts, setPodcasts] = useState([])
  const [limit, setLimit]       = useState({ used: 0, limit: 3 })
  const [schedule, setSchedule] = useState(null)
  const [running, setRunning]   = useState(false)
  const [runMsg, setRunMsg]     = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)

  const fetchAll = useCallback(async () => {
    try {
      const [statsRes, podRes, limitRes, schedRes] = await Promise.all([
        fetch(`${API}/api/stats`).then(r => r.json()),
        fetch(`${API}/api/podcasts?limit=50`).then(r => r.json()),
        fetch(`${API}/api/daily-limit`).then(r => r.json()),
        fetch(`${API}/api/schedule`).then(r => r.json()),
      ])
      setStats(statsRes)
      setPodcasts(podRes.podcasts || [])
      setLimit(limitRes)
      setSchedule(schedRes)
      setLastRefresh(new Date().toLocaleTimeString())
    } catch (err) {
      console.error('Fetch error:', err)
    }
  }, [])

  // Poll run status while pipeline is running
  useEffect(() => {
    if (!running) return
    const interval = setInterval(async () => {
      try {
        const res  = await fetch(`${API}/api/run/status`).then(r => r.json())
        if (!res.running) {
          setRunning(false)
          setRunMsg('Pipeline finished!')
          setTimeout(() => setRunMsg(null), 4000)
          fetchAll()
        }
      } catch {}
    }, 3000)
    return () => clearInterval(interval)
  }, [running, fetchAll])

  // Auto-refresh every 30 seconds
  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 30000)
    return () => clearInterval(interval)
  }, [fetchAll])

  const handleRunNow = async () => {
    if (running) return
    try {
      const res = await fetch(`${API}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count: 1 }),
      }).then(r => r.json())

      if (res.status === 'already_running') {
        setRunMsg('Already running!')
        setTimeout(() => setRunMsg(null), 3000)
        return
      }
      setRunning(true)
      setRunMsg('Pipeline started...')
    } catch (err) {
      setRunMsg(`Error: ${err.message}`)
      setTimeout(() => setRunMsg(null), 4000)
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-200">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🎙️</span>
          <div>
            <h1 className="text-lg font-bold text-white leading-tight">AI Podcast Pipeline</h1>
            <p className="text-xs text-slate-400">
              Cron: <span className="font-mono text-slate-300">{schedule?.cron ?? '…'}</span>
              {lastRefresh && <span className="ml-3">Last refresh: {lastRefresh}</span>}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {runMsg && (
            <span className={`text-sm px-3 py-1 rounded-lg ${running ? 'bg-blue-700 text-blue-100' : 'bg-green-700 text-green-100'}`}>
              {runMsg}
            </span>
          )}
          <button
            onClick={handleRunNow}
            disabled={running}
            className={`px-5 py-2 rounded-lg font-semibold text-sm transition-all ${
              running
                ? 'bg-slate-600 text-slate-400 cursor-not-allowed'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg'
            }`}
          >
            {running ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"/>
                Running…
              </span>
            ) : '▶ Run Now'}
          </button>
        </div>
      </header>

      <main className="px-6 py-6 max-w-7xl mx-auto space-y-6">
        {/* ── Stat Cards ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Total Episodes"  value={stats?.total_podcasts} color="text-white" />
          <StatCard label="Published"       value={stats?.published}      color="text-green-400" />
          <StatCard label="Failed"          value={stats?.failed}         color="text-red-400" />
          <StatCard label="Today's Count"   value={stats?.today_count}    color="text-blue-400" />
        </div>

        {/* ── Daily Limit + Chart ─────────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <DailyLimit used={limit.used} limit={limit.limit} />
          <div className="bg-slate-800 rounded-xl p-5 shadow">
            <h2 className="text-slate-400 text-sm mb-4">Last 7 Days</h2>
            <BarChart days={stats?.recent_days} />
          </div>
        </div>

        {/* ── Episode Table ────────────────────────────────────────────── */}
        <div className="bg-slate-800 rounded-xl p-5 shadow">
          <h2 className="text-white font-semibold mb-4">
            All Episodes
            <span className="ml-2 text-slate-400 font-normal text-sm">({podcasts.length})</span>
          </h2>
          <PodcastTable podcasts={podcasts} />
        </div>

        {/* ── API Request Log ──────────────────────────────────────────── */}
        <div className="bg-slate-800 rounded-xl p-5 shadow">
          <h2 className="text-white font-semibold mb-4">Live API Request Log <span className="text-slate-400 font-normal text-sm">(last 20)</span></h2>
          <RequestLog requests={stats?.recent_requests} />
        </div>
      </main>
    </div>
  )
}
