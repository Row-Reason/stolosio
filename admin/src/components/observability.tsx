import { ArrowRight, LoaderCircle, RefreshCw } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { extractApiError } from "@/lib/api"
import { number } from "@/lib/observability"
import { cn } from "@/lib/utils"
import type { OutcomeBucket, OverviewWindow } from "@/types/api"

export function WindowPicker({
  value,
  onChange,
}: {
  value: OverviewWindow
  onChange: (value: OverviewWindow) => void
}) {
  return (
    <div
      className="inline-flex rounded-lg border bg-card p-1"
      role="group"
      aria-label="Time period"
    >
      {(
        [
          ["24h", "24 hours"],
          ["7d", "7 days"],
          ["30d", "30 days"],
        ] as const
      ).map(([key, label]) => (
        <Button
          key={key}
          size="sm"
          variant={value === key ? "secondary" : "ghost"}
          aria-pressed={value === key}
          onClick={() => onChange(key)}
        >
          {label}
        </Button>
      ))}
    </div>
  )
}

export function Metric({
  label,
  value,
  detail,
  href,
  navigate,
}: {
  label: string
  value: string
  detail?: string
  href?: string
  navigate?: (href: string) => void
}) {
  const contents = (
    <>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">
        {value}
      </p>
      {detail && (
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
      )}
    </>
  )
  return href && navigate ? (
    <button
      type="button"
      onClick={() => navigate(href)}
      className="rounded-lg border bg-card p-4 text-left transition-colors hover:bg-muted/40"
    >
      {contents}
    </button>
  ) : (
    <div className="rounded-lg border bg-card p-4">{contents}</div>
  )
}

export function Section({
  title,
  description,
  action,
  children,
}: {
  title: string
  description?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-xl border bg-card">
      <div className="flex items-start justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 className="font-semibold">{title}</h2>
          {description && (
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function QueryMessage({
  loading,
  error,
  retry,
}: {
  loading?: boolean
  error?: unknown
  retry?: () => void
}) {
  if (loading)
    return (
      <div
        className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground"
        role="status"
      >
        <LoaderCircle className="size-4 animate-spin" />
        Loading observations…
      </div>
    )
  return (
    <div className="p-5" role="alert">
      <p className="text-sm font-medium">Observations unavailable</p>
      <p className="mt-1 text-sm text-muted-foreground">
        {extractApiError(error)}
      </p>
      {retry && (
        <Button className="mt-3" variant="outline" size="sm" onClick={retry}>
          <RefreshCw />
          Try again
        </Button>
      )}
    </div>
  )
}

export function OutcomesChart({ series }: { series: OutcomeBucket[] }) {
  const peak = Math.max(
    1,
    ...series.map((row) => row.success + row.failed + row.other)
  )
  const total = series.reduce(
    (sum, row) => sum + row.success + row.failed + row.other,
    0
  )
  return (
    <div>
      <div
        className="flex h-24 items-end gap-1"
        role="img"
        aria-label={`Outcomes over time: ${number(series.reduce((n, r) => n + r.success, 0))} completed, ${number(series.reduce((n, r) => n + r.failed, 0))} failed, ${number(series.reduce((n, r) => n + r.other, 0))} other.`}
      >
        {series.map((row) => (
          <div
            key={row.at}
            className="flex h-full min-w-0 flex-1 flex-col justify-end"
            title={`${new Date(row.at).toLocaleString()} · ${row.success} completed · ${row.failed} failed · ${row.other} other`}
          >
            {row.other > 0 && (
              <div
                className="rounded-t-sm bg-amber-400/80"
                style={{ height: `${(row.other / peak) * 100}%` }}
              />
            )}
            {row.failed > 0 && (
              <div
                className="bg-rose-500/80"
                style={{ height: `${(row.failed / peak) * 100}%` }}
              />
            )}
            {row.success > 0 && (
              <div
                className="bg-emerald-500/75"
                style={{ height: `${(row.success / peak) * 100}%` }}
              />
            )}
            {!(row.success + row.failed + row.other) && (
              <div className="h-px bg-muted-foreground/20" />
            )}
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-muted-foreground">
        <span>
          {series[0] &&
            new Date(series[0].at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
            })}
        </span>
        <span>
          {total
            ? "By completion time · UTC buckets"
            : "No completed work in this period"}
        </span>
        <span>Now</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
        {[
          ["Completed", "bg-emerald-500"],
          ["Failed", "bg-rose-500"],
          ["Other / rejected", "bg-amber-400"],
        ].map(([label, color]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", color)} />
            {label}
          </span>
        ))}
      </div>
      <details className="mt-3 text-xs text-muted-foreground">
        <summary className="cursor-pointer">View counts over time</summary>
        <div className="mt-2 max-h-48 overflow-auto">
          <table className="w-full text-left">
            <thead>
              <tr>
                <th>UTC bucket</th>
                <th>Completed</th>
                <th>Failed</th>
                <th>Other</th>
              </tr>
            </thead>
            <tbody>
              {series.map((row) => (
                <tr key={row.at}>
                  <td className="py-1">
                    {new Date(row.at)
                      .toISOString()
                      .slice(0, 16)
                      .replace("T", " ")}
                  </td>
                  <td>{row.success}</td>
                  <td>{row.failed}</td>
                  <td>{row.other}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}

export function ViewLink({
  label,
  href,
  navigate,
}: {
  label: string
  href: string
  navigate: (href: string) => void
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => navigate(href)}
      className="shrink-0 text-muted-foreground"
    >
      {label}
      <ArrowRight className="size-3.5" />
    </Button>
  )
}
