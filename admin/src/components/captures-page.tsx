import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { extractApiError } from "@/lib/api"
import type { CaptureAcquisitionOutcome, CaptureOverview, CaptureStats } from "@/types/api"

const labels: Record<CaptureAcquisitionOutcome, string> = {
  default: "Default acquisition",
  internally_resolved: "Internally resolved",
  externally_resolved: "Externally resolved",
  total_failure: "Total failure",
}
const percentage = (value: number | null) => value === null ? "—" : `${(value * 100).toFixed(1)}%`

function StatsPanel({ title, stats }: { title: string; stats: CaptureStats }) {
  return <Card className="p-6">
    <h2 className="text-lg font-semibold">{title}</h2>
    <p className="text-sm text-muted-foreground">{stats.total.toLocaleString()} completed captures</p>
    <div className="mt-5 space-y-4">
      {(Object.keys(labels) as CaptureAcquisitionOutcome[]).map(outcome => <div key={outcome}>
        <div className="flex justify-between text-sm"><span>{labels[outcome]}</span>
          <span>{stats.counts[outcome].toLocaleString()} · {percentage(stats.rates[outcome])}</span></div>
        <div className="mt-2 h-2 overflow-hidden rounded bg-muted"><div className="h-full bg-primary"
          style={{ width: `${(stats.rates[outcome] ?? 0) * 100}%` }} /></div>
      </div>)}
    </div>
    <dl className="mt-6 grid grid-cols-2 gap-3 border-t pt-4 text-sm">
      <dt>Local attempts</dt><dd>{stats.local_attempts.toLocaleString()}</dd>
      <dt>External attempts</dt><dd>{stats.external_attempts.toLocaleString()}</dd>
      <dt>Local success per attempt</dt><dd>{percentage(stats.local_attempts ? stats.counts.internally_resolved / stats.local_attempts : null)}</dd>
      <dt>Local resolver time</dt><dd>{stats.local_seconds.toFixed(1)} s</dd>
      <dt>External resolver time</dt><dd>{stats.external_seconds.toFixed(1)} s</dd>
      <dt>Captures using paid service</dt><dd>{stats.paid_captures.toLocaleString()}</dd>
      <dt>Mean capture duration</dt><dd>{stats.mean_duration_ms === null ? "—" : `${(stats.mean_duration_ms / 1000).toFixed(1)} s`}</dd>
    </dl>
  </Card>
}

export function CapturesPage() {
  const [window, setWindow] = useState("7d")
  const query = useQuery({
    queryKey: ["capture-analytics", window],
    queryFn: async (): Promise<CaptureOverview> => {
      const response = await fetch(`/v1/admin/captures/overview?window=${window}`)
      if (!response.ok) throw new Error(extractApiError(await response.json().catch(() => undefined)))
      return response.json() as Promise<CaptureOverview>
    },
    refetchInterval: 15000,
  })
  return <main className="space-y-6 p-6">
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div><h1 className="text-2xl font-semibold">Capture outcomes</h1>
        <p className="text-sm text-muted-foreground">Acquisition across all downstream clients.</p></div>
      <div className="flex gap-2">{["24h", "7d", "30d", "90d"].map(value =>
        <Button key={value} variant={value === window ? "default" : "outline"} onClick={() => setWindow(value)}>{value}</Button>)}</div>
    </div>
    {query.isPending && <p>Loading capture outcomes…</p>}
    {query.isError && <p role="alert">{extractApiError(query.error)}</p>}
    {query.data && <>
      <div className="grid gap-6 xl:grid-cols-2">
        <StatsPanel title="All captures" stats={query.data.all_captures} />
        <StatsPanel title="Detected challenges with resolution enabled" stats={query.data.challenged_opt_in} />
      </div>
      <p className="text-sm text-muted-foreground">Counts follow the source of accepted content, not the last attempted tier.
        Normal acquisition that clears a challenge remains default. API acceptance does not guarantee downstream usefulness.
        Admission refusals and disconnected requests without a completed result are excluded.
        {query.data.tracking_since ? ` Tracking started ${new Date(query.data.tracking_since).toLocaleString()}.` : " No tracked captures yet."}
      </p>
    </>}
  </main>
}
