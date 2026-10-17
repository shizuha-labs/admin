import { useEffect, useState } from 'react'

function Coin({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <defs>
        <radialGradient id="admin-hane-face" cx="35%" cy="30%" r="75%">
          <stop offset="0%" stopColor="#ffe9a8" />
          <stop offset="45%" stopColor="#f5c14a" />
          <stop offset="100%" stopColor="#b8860b" />
        </radialGradient>
      </defs>
      <circle cx="16" cy="16" r="15" fill="#d4a017" />
      <circle cx="16" cy="16" r="12.5" fill="url(#admin-hane-face)" />
    </svg>
  )
}

function formatHane(n) {
  return Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

export default function HaneChip() {
  const [hane, setHane] = useState(null)

  useEffect(() => {
    const token = localStorage.getItem('shizuha_access_token') || ''
    if (!token) return undefined
    let cancelled = false
    fetch('/v1/hane', { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data && typeof data.available === 'number') setHane(data)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const available = hane?.available
  const fiat = hane?.fiat?.label
  return (
    <a
      href="https://cortex.shizuha.com/cortex/usage#hane"
      className="inline-flex items-center gap-1.5 rounded-full border border-amber-400/40 bg-amber-50 px-2.5 py-1 no-underline dark:bg-amber-950/40 dark:border-amber-500/30"
      title={available == null ? 'Hane ledger' : `${formatHane(available)} Hane${fiat ? ` · ${fiat}` : ''}`}
    >
      <Coin />
      <span className="font-mono text-xs font-semibold tabular-nums text-amber-800 dark:text-amber-200">
        {available == null ? '—' : formatHane(available)}
      </span>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-400">Hane</span>
      {fiat ? <span className="font-mono text-[10px] tabular-nums text-amber-700/80 dark:text-amber-300/80">{fiat}</span> : null}
    </a>
  )
}
