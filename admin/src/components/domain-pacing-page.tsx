import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowUpRight, RefreshCw, Settings2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Metric, Section } from "@/components/observability"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiRequest, extractApiError } from "@/lib/api"
import type {
  PacingBucket,
  PacingDashboard,
  PacingDomain,
  PacingWindow,
} from "@/types/api"

const rate = (value: number) =>
  `${value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")}/s`
const seconds = (value: number) => `${Number(value.toFixed(3))} s`
const time = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "—"
const refused = (domain: PacingDomain) =>
  Object.values(domain.traffic.refusals).reduce((a, b) => a + b, 0)
const reasons: Record<string, string> = {
  default: "Starting allowance",
  healthy_at_limit: "Healthy responses near allowance",
  origin_throttled: "Target throttling observed",
  origin_overload: "Repeated target overload observed",
  ttl_expired: "Learned allowance expired",
  settings_changed: "Global settings changed",
  operator_reset: "Operator requested reset",
}

function pacingState(domain: PacingDomain, data: PacingDashboard) {
  if (domain.cooldown_until && domain.cooldown_until > data.ends_at)
    return "Cooldown"
  if (domain.reset_requested) return "Reset pending"
  if (domain.expired) return "Expired · using defaults"
  if (
    domain.effective_concurrency >= data.settings.maximum_concurrency &&
    domain.effective_spacing_seconds <= data.settings.minimum_spacing_seconds
  )
    return "Configured bounds reached"
  if (!domain.traffic.offered) return "No demand in window"
  if (refused(domain) || domain.healthy_samples) return "Learning"
  return "Demand below allowance"
}

type Line = {
  label: string
  color: string
  value: (bucket: PacingBucket) => number | null
}

function HistoryChart({
  title,
  description,
  data,
  lines,
  unit,
}: {
  title: string
  description: string
  data: PacingBucket[]
  lines: Line[]
  unit: string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const values = data.flatMap((bucket) =>
    lines
      .map((line) => line.value(bucket))
      .filter((v): v is number => v !== null)
  )
  const max = Math.max(...values, 1)
  const x = (index: number) => 45 + (index / Math.max(1, data.length - 1)) * 640
  const y = (value: number) => 145 - (value / max) * 125
  const selected = hover === null ? null : data[hover]
  return (
    <Section title={title} description={description}>
      <div className="p-4">
        <div className="mb-3 flex flex-wrap gap-x-5 gap-y-2 text-xs">
          {lines.map((line) => (
            <span key={line.label} className="flex items-center gap-2">
              <span className="h-0.5 w-4" style={{ background: line.color }} />
              {line.label}
            </span>
          ))}
        </div>
        {!values.length ? (
          <div className="flex h-44 items-center justify-center text-sm text-muted-foreground">
            No measurements in this window.
          </div>
        ) : (
          <svg
            viewBox="0 0 700 180"
            className="w-full"
            role="img"
            aria-label={title}
            onMouseLeave={() => setHover(null)}
          >
            {[0, 0.5, 1].map((fraction) => (
              <g key={fraction}>
                <line
                  x1="45"
                  x2="685"
                  y1={y(max * fraction)}
                  y2={y(max * fraction)}
                  stroke="currentColor"
                  className="text-border"
                />
                <text
                  x="38"
                  y={y(max * fraction) + 4}
                  textAnchor="end"
                  fill="currentColor"
                  className="text-muted-foreground"
                  fontSize="10"
                >
                  {Number((max * fraction).toFixed(2))}
                </text>
              </g>
            ))}
            {lines.map((line) => {
              let path = ""
              let connected = false
              data.forEach((bucket, index) => {
                const value = line.value(bucket)
                if (value === null) {
                  connected = false
                  return
                }
                path += `${connected ? "L" : "M"}${x(index)},${y(value)} `
                connected = true
              })
              return (
                <g key={line.label}>
                  <path
                    d={path}
                    fill="none"
                    stroke={line.color}
                    strokeWidth="2"
                  />
                  {data.map((bucket, index) => {
                    const value = line.value(bucket)
                    return value === null ? null : (
                      <circle
                        key={bucket.at}
                        cx={x(index)}
                        cy={y(value)}
                        r="2"
                        fill={line.color}
                      />
                    )
                  })}
                </g>
              )
            })}
            {hover !== null && (
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1="15"
                y2="145"
                stroke="currentColor"
                className="text-muted-foreground"
                strokeDasharray="3 3"
              />
            )}
            {data.map((bucket, index) => (
              <rect
                key={bucket.at}
                x={x(index) - 640 / data.length / 2}
                y="15"
                width={640 / data.length}
                height="135"
                fill="transparent"
                onMouseEnter={() => setHover(index)}
              >
                <title>
                  {time(bucket.at)}
                  {lines
                    .map(
                      (line) =>
                        `\n${line.label}: ${line.value(bucket) ?? "No measurement"} ${unit}`
                    )
                    .join("")}
                </title>
              </rect>
            ))}
            <text
              x="45"
              y="170"
              fontSize="10"
              fill="currentColor"
              className="text-muted-foreground"
            >
              {data[0] &&
                new Date(data[0].at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
            </text>
            <text
              x="685"
              y="170"
              textAnchor="end"
              fontSize="10"
              fill="currentColor"
              className="text-muted-foreground"
            >
              {data.at(-1) &&
                new Date(data.at(-1)!.at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
            </text>
          </svg>
        )}
        <p className="min-h-5 text-xs text-muted-foreground" aria-live="polite">
          {selected
            ? `${time(selected.at)} · ${lines.map((line) => `${line.label}: ${line.value(selected) === null ? "—" : Number(line.value(selected)!.toFixed(3))} ${unit}`).join(" · ")}`
            : "Hover over the chart to inspect a time bucket."}
        </p>
      </div>
    </Section>
  )
}

function HostDetails({
  data,
  domain,
}: {
  data: PacingDashboard
  domain: PacingDomain
}) {
  const client = useQueryClient()
  const [confirmReset, setConfirmReset] = useState(false)
  const reset = useMutation({
    mutationFn: () =>
      apiRequest(
        `/v1/admin/domain-pacing/reset?hostname=${encodeURIComponent(domain.hostname)}`,
        { method: "POST" }
      ),
    onSuccess: () => {
      setConfirmReset(false)
      toast.success(
        "Starting limits will apply on the next capture. Existing cooldown is preserved."
      )
      void client.invalidateQueries({ queryKey: ["pacing-dashboard"] })
      void client.invalidateQueries({ queryKey: ["domain-pacing"] })
    },
    onError: (error) => toast.error(extractApiError(error)),
  })
  const healthy = domain.expired ? 0 : domain.healthy_samples
  const concurrency = domain.expired ? 0 : domain.concurrency_samples
  const series = data.tracking_since
    ? data.series.filter(
        (bucket) =>
          new Date(bucket.at).getTime() + data.bucket_seconds * 1000 >
          new Date(data.tracking_since!).getTime()
      )
    : []
  const needed = Math.ceil(data.settings.healthy_samples / 2)
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <Metric
          label="Occupied / allowed now"
          value={`${domain.active_captures} / ${domain.effective_concurrency}`}
          detail="Shared across all capture callers"
        />
        <Metric
          label="Minimum spacing now"
          value={seconds(domain.effective_spacing_seconds)}
          detail={`At most ${rate(1 / domain.effective_spacing_seconds)} capture starts from spacing alone`}
        />
        <Metric
          label="Controller state"
          value={pacingState(domain, data)}
          detail={
            domain.cooldown_until && domain.cooldown_until > data.ends_at
              ? `Cooldown until ${time(domain.cooldown_until)}`
              : `Allowance expires ${time(domain.expires_at)}`
          }
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <HistoryChart
          title="Demand and admitted starts"
          description="API attempts include retries. Rates describe capture starts, not individual website requests."
          data={series}
          unit="/s"
          lines={[
            {
              label: "Offered",
              color: "#a78bfa",
              value: (b) => b.offered_per_second,
            },
            {
              label: "Admitted",
              color: "#34d399",
              value: (b) => b.admitted_per_second,
            },
          ]}
        />
        <HistoryChart
          title="Occupied slots and allowance"
          description="Peak occupied slots and maximum allowance sampled at admission decisions; gaps mean no samples."
          data={series}
          unit="captures"
          lines={[
            {
              label: "Occupied (sampled peak)",
              color: "#38bdf8",
              value: (b) => b.peak_active,
            },
            {
              label: "Allowed (sampled maximum)",
              color: "#a78bfa",
              value: (b) => b.maximum_allowance,
            },
          ]}
        />
        <HistoryChart
          title="Start spacing"
          description="Smallest observed minimum spacing in each bucket. This is a policy setting."
          data={series}
          unit="s"
          lines={[
            {
              label: "Minimum spacing",
              color: "#a78bfa",
              value: (b) => b.minimum_spacing_seconds,
            },
          ]}
        />
        <HistoryChart
          title="Target response signals"
          description="Completed captures classified by the pacing controller. These are separate from Stolosio refusals."
          data={series}
          unit="results"
          lines={[
            {
              label: "Target throttling",
              color: "#fb7185",
              value: (b) => b.origin_throttled,
            },
            {
              label: "Target overload",
              color: "#fbbf24",
              value: (b) => b.origin_overload,
            },
          ]}
        />
        <HistoryChart
          title="Stolosio refusals"
          description="Requests refused before any target acquisition, grouped by admission reason."
          data={series}
          unit="refusals"
          lines={[
            {
              label: "Spacing",
              color: "#a78bfa",
              value: (b) => b.refusals.domain_spacing,
            },
            {
              label: "Concurrency",
              color: "#38bdf8",
              value: (b) => b.refusals.domain_concurrency,
            },
            {
              label: "Cooldown",
              color: "#fb7185",
              value: (b) => b.refusals.domain_cooldown,
            },
          ]}
        />
        <HistoryChart
          title="Capture slot duration"
          description="Mean time from admission to release; includes provider waits and rendering. This is not target latency."
          data={series}
          unit="s"
          lines={[
            {
              label: "Mean slot duration",
              color: "#38bdf8",
              value: (b) => b.mean_capture_seconds,
            },
          ]}
        />
      </div>
      <Section
        title="Learning progress"
        description="Only healthy responses near the allowance count toward an increase."
      >
        <div className="grid gap-6 p-5 md:grid-cols-2">
          <div>
            <div className="flex justify-between text-sm">
              <span>Healthy qualifying samples</span>
              <span>
                {healthy} / {data.settings.healthy_samples}
              </span>
            </div>
            <progress
              aria-label="Healthy qualifying samples"
              value={healthy}
              max={data.settings.healthy_samples}
              className="mt-3 h-2 w-full accent-emerald-500"
            />
            <p className="mt-3 text-xs text-muted-foreground">
              Concurrency pressure: {concurrency} samples; at least {needed}{" "}
              required for a concurrency increase. Otherwise the next increase
              reduces spacing by 20%, within configured bounds.
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-muted-foreground">Concurrency ceiling</dt>
            <dd>{data.settings.maximum_concurrency}</dd>
            <dt className="text-muted-foreground">Spacing floor</dt>
            <dd>{seconds(data.settings.minimum_spacing_seconds)}</dd>
            <dt className="text-muted-foreground">Overload streak</dt>
            <dd>
              {domain.expired ? 0 : domain.overload_samples} /{" "}
              {data.settings.overload_samples}
            </dd>
            <dt className="text-muted-foreground">Learned TTL</dt>
            <dd>{data.settings.learned_ttl_seconds / 3600} hours</dd>
          </dl>
        </div>
        <p className="border-t px-5 py-3 text-xs text-muted-foreground">
          An allowance is a learned operating limit. Healthy responses without
          enough demand do not establish a site’s maximum capacity.
        </p>
      </Section>
      <Section
        title="Adjustment history"
        description="Up to 100 retained changes in the selected window, newest first. Each row records the applied limits."
      >
        {!data.history.length ? (
          <p className="p-5 text-sm text-muted-foreground">
            No retained adjustments in this window.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b text-xs text-muted-foreground">
                <tr>
                  {[
                    "Time",
                    "Applied concurrency",
                    "Applied spacing",
                    "Observed reason",
                  ].map((label) => (
                    <th key={label} className="px-5 py-3 font-medium">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.history.map((event) => (
                  <tr
                    key={`${event.at}-${event.generation}`}
                    className="border-b last:border-0"
                  >
                    <td className="px-5 py-3 whitespace-nowrap">
                      {time(event.at)}
                    </td>
                    <td className="px-5 py-3">{event.concurrency}</td>
                    <td className="px-5 py-3">
                      {seconds(event.spacing_seconds)}
                    </td>
                    <td className="px-5 py-3">
                      {reasons[event.reason] ?? event.reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {confirmReset ? (
          <>
            <span>
              Use starting limits on the next capture? Active captures and
              cooldown stay in place.
            </span>
            <Button
              variant="outline"
              disabled={reset.isPending}
              onClick={() => reset.mutate()}
            >
              Confirm reset
            </Button>
            <Button variant="ghost" onClick={() => setConfirmReset(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <Button
            variant="outline"
            disabled={domain.reset_requested}
            onClick={() => setConfirmReset(true)}
          >
            Reset learned allowance
          </Button>
        )}
      </div>
    </div>
  )
}

export function DomainPacingPage({
  hostname,
  navigate,
}: {
  hostname?: string
  navigate: (href: string) => void
}) {
  const [period, setPeriod] = useState<PacingWindow>("1h")
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState("all")
  const query = useQuery({
    queryKey: ["pacing-dashboard", period, hostname],
    queryFn: () =>
      apiRequest<PacingDashboard>(
        `/v1/admin/domain-pacing/dashboard?window=${period}${hostname ? `&hostname=${encodeURIComponent(hostname)}` : ""}`
      ),
    refetchInterval: 10000,
  })
  const data = query.data
  const selected = data?.domains[0]
  const hosts = data?.domains
    .filter(
      (domain) =>
        domain.hostname.includes(search.toLowerCase()) &&
        (filter === "all" ||
          (filter === "cooldown"
            ? pacingState(domain, data) === "Cooldown"
            : refused(domain) > 0))
    )
    .sort(
      (a, b) =>
        b.traffic.offered - a.traffic.offered ||
        a.hostname.localeCompare(b.hostname)
    )
  return (
    <main className="mx-auto max-w-[1600px] space-y-6 p-5 md:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Button
            variant="ghost"
            size="sm"
            className="mb-2 -ml-3"
            onClick={() =>
              navigate(hostname ? "/captures/pacing" : "/captures")
            }
          >
            <ArrowLeft />
            {hostname ? "All hosts" : "Captures"}
          </Button>
          <h1 className="text-3xl font-semibold tracking-tight">
            {hostname ?? "Domain pacing"}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {hostname
              ? "Shared capture allowance, demand, and controller evidence."
              : "See where capture demand meets a host’s learned allowance."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div
            role="group"
            aria-label="Time window"
            className="flex rounded-lg border p-1"
          >
            {(["1h", "24h", "7d"] as const).map((value) => (
              <Button
                key={value}
                size="sm"
                aria-pressed={period === value}
                variant={period === value ? "secondary" : "ghost"}
                onClick={() => setPeriod(value)}
              >
                {value}
              </Button>
            ))}
          </div>
          <Button
            variant="outline"
            size="icon"
            aria-label="Refresh pacing dashboard"
            onClick={() => void query.refetch()}
          >
            <RefreshCw className={query.isFetching ? "animate-spin" : ""} />
          </Button>
          <Button variant="outline" onClick={() => navigate("/policy")}>
            <Settings2 />
            Global settings
          </Button>
        </div>
      </div>
      {query.isError && (
        <p role="alert" className="text-destructive">
          {extractApiError(query.error)}
        </p>
      )}
      {query.isPending && <p role="status">Loading domain pacing…</p>}
      {data && (
        <>
          {!hostname && (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Metric
                label="Active hosts now"
                value={String(data.totals.active_hosts)}
                detail="At least one capture slot occupied"
              />
              <Metric
                label="Hosts throttled by Stolosio"
                value={String(data.totals.throttled_hosts)}
                detail={`Admission refusals during ${period}`}
              />
              <Metric
                label="Hosts in cooldown now"
                value={String(data.totals.cooldown_hosts)}
                detail="Backoff following target response signals"
              />
              <Metric
                label="Target throttling results"
                value={String(data.totals.origin_throttled)}
                detail={`Completed capture signals during ${period}`}
              />
            </div>
          )}
          <div className="flex flex-wrap gap-x-6 gap-y-2 rounded-lg border bg-muted/20 px-4 py-3 text-sm">
            <span>
              <strong>{data.totals.offered.toLocaleString()}</strong> offered
              attempts
            </span>
            <span>
              <strong>{data.totals.admitted.toLocaleString()}</strong> admitted
              captures
            </span>
            <span>
              <strong>
                {Object.values(data.totals.refusals)
                  .reduce((a, b) => a + b, 0)
                  .toLocaleString()}
              </strong>{" "}
              Stolosio refusals
            </span>
            <span>
              <strong>{data.totals.origin_throttled}</strong> target throttling
            </span>
            <span>
              <strong>{data.totals.origin_overload}</strong> target overload
            </span>
          </div>
          {hostname ? (
            selected ? (
              <HostDetails key={hostname} data={data} domain={selected} />
            ) : (
              <p>No learned policy for this hostname.</p>
            )
          ) : (
            <Section
              title="Hosts"
              description="Rates are averages over the selected window. Choose a host to inspect traffic and learning."
            >
              <div className="flex flex-wrap gap-3 border-b p-4">
                <Input
                  className="max-w-sm"
                  aria-label="Filter hostnames"
                  placeholder="Filter hostnames…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <div className="flex gap-1">
                  {[
                    ["all", "All"],
                    ["throttled", "Stolosio throttled"],
                    ["cooldown", "In cooldown"],
                  ].map(([value, label]) => (
                    <Button
                      key={value}
                      variant={filter === value ? "secondary" : "ghost"}
                      aria-pressed={filter === value}
                      onClick={() => setFilter(value)}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              </div>
              {!hosts?.length ? (
                <p className="p-6 text-sm text-muted-foreground">
                  No matching hosts. Learned policies appear after capture
                  requests.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b text-xs text-muted-foreground">
                      <tr>
                        {[
                          "Hostname",
                          "Demand",
                          "Admitted",
                          "Occupied / allowed",
                          "Spacing",
                          "State",
                          "Last adjustment",
                        ].map((label) => (
                          <th
                            key={label}
                            className="px-4 py-3 font-medium whitespace-nowrap"
                          >
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {hosts.map((domain) => (
                        <tr
                          key={domain.hostname}
                          className="border-b last:border-0 hover:bg-muted/30"
                        >
                          <td className="px-4 py-4">
                            <button
                              className="flex items-center gap-2 font-medium text-primary hover:underline"
                              onClick={() =>
                                navigate(
                                  `/captures/pacing/${encodeURIComponent(domain.hostname)}`
                                )
                              }
                            >
                              {domain.hostname}
                              <ArrowUpRight className="size-3" />
                            </button>
                          </td>
                          <td className="px-4 py-4 tabular-nums">
                            {rate(domain.offered_per_second)}
                          </td>
                          <td className="px-4 py-4 tabular-nums">
                            {rate(domain.admitted_per_second)}
                          </td>
                          <td className="px-4 py-4 tabular-nums">
                            {domain.active_captures} /{" "}
                            {domain.effective_concurrency}
                          </td>
                          <td className="px-4 py-4 whitespace-nowrap">
                            {seconds(domain.effective_spacing_seconds)}
                          </td>
                          <td className="px-4 py-4">
                            <Badge variant="outline">
                              {pacingState(domain, data)}
                            </Badge>
                          </td>
                          <td className="px-4 py-4 text-xs">
                            <span>
                              {reasons[domain.reason] ?? domain.reason}
                            </span>
                            <span className="mt-1 block text-muted-foreground">
                              {time(domain.adjusted_at)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data.domains_truncated && (
                <p className="border-t p-4 text-xs text-muted-foreground">
                  Showing the first 500 learned hosts alphabetically. Hostname
                  filtering searches this displayed set.
                </p>
              )}
            </Section>
          )}
          <p className="text-xs leading-5 text-muted-foreground">
            Capture-level pacing does not limit individual browser requests or
            CDP sessions. Offered demand includes retries and excludes requests
            refused by global admission before domain pacing.{" "}
            {data.tracking_since
              ? `Earliest retained traffic measurement: ${time(data.tracking_since)}. `
              : "Traffic measurement starts with the next capture. "}
            Traffic facts are retained for 7 days; adjustment history follows
            event retention. Updated {time(data.ends_at)}.
          </p>
        </>
      )}
    </main>
  )
}
