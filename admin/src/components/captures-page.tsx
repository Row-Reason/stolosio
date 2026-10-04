import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  FileText,
  Search,
} from "lucide-react"
import { useEffect, useState } from "react"

import {
  Metric,
  QueryMessage,
  Section,
  ViewLink,
  WindowPicker,
} from "@/components/observability"
import {
  duration,
  fetchJson,
  humanize,
  number,
  pathLabels,
  percent,
  plural,
  useOverview,
} from "@/lib/observability"
import { CaptureAnalyticsPanel } from "@/components/capture-analytics-panel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type {
  CaptureAttempt,
  OverviewWindow,
  SessionDetail,
  SessionPage,
} from "@/types/api"

const outcomeLabels: Record<string, string> = {
  captured: "Captured",
  failed: "Failed",
  rejected: "Rejected",
  interrupted: "Interrupted",
  in_progress: "In progress",
  unknown: "Result unavailable",
}
const reasonLabels: Record<CaptureAttempt["reason"], string> = {
  cache_url:
    "Previous comparisons confirmed that HTTP is sufficient for this page.",
  cache_pattern:
    "Comparisons for this URL pattern support using HTTP without rendering.",
  canary:
    "A cached page was rendered again to check that HTTP is still sufficient.",
  verify_http:
    "Rendered to check whether the HTTP response includes the page’s content.",
  assessment: "The response was assessed before choosing the next step.",
  content_comparison:
    "Compared the rendered content with the original HTTP response.",
  acquisition: "Page acquisition attempt.",
  media_type: "The response’s media type can be returned without rendering.",
}

export function CaptureOutcome({ value }: { value: string | null }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "whitespace-nowrap",
        value === "captured" &&
          "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
        value === "failed" &&
          "border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-400",
        (value === "rejected" || value === "interrupted") &&
          "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-400"
      )}
    >
      {outcomeLabels[value ?? "unknown"]}
    </Badge>
  )
}

function initialWindow(): OverviewWindow {
  const value = new URLSearchParams(window.location.search).get("window")
  return value === "7d" || value === "30d" ? value : "24h"
}

function CaptureList({ navigate }: { navigate: (href: string) => void }) {
  const params = new URLSearchParams(window.location.search)
  const [period, setPeriod] = useState<OverviewWindow>(initialWindow)
  const [outcome, setOutcome] = useState(params.get("outcome") ?? "all")
  const [reason, setReason] = useState(params.get("reason") ?? "")
  const [path, setPath] = useState(params.get("path") ?? "all")
  const [searchInput, setSearchInput] = useState(params.get("search") ?? "")
  const [search, setSearch] = useState(params.get("search") ?? "")
  const overview = useOverview(period)
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 250)
    return () => clearTimeout(timer)
  }, [searchInput])
  const query = new URLSearchParams({
    workload: "capture",
    limit: "50",
    window: period,
  })
  if (outcome !== "all") query.set("outcome", outcome)
  if (path !== "all") query.set("path", path)
  if (search) query.set("search", search)
  if (reason) query.set("reason", reason)
  const queryString = query.toString()
  const list = useInfiniteQuery({
    queryKey: ["captures", queryString],
    queryFn: ({ pageParam }) =>
      fetchJson<SessionPage>(
        `/v1/admin/sessions?${queryString}${pageParam ? `&before=${encodeURIComponent(pageParam)}` : ""}`
      ),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: 10_000,
  })
  const rows = list.data?.pages.flatMap((page) => page.sessions) ?? []
  const data = overview.data?.capture
  const filterParams = new URLSearchParams({ window: period })
  if (outcome !== "all") filterParams.set("outcome", outcome)
  if (path !== "all") filterParams.set("path", path)
  if (search) filterParams.set("search", search)
  if (reason) filterParams.set("reason", reason)
  const listUrl = filterParams.toString()
  useEffect(() => {
    window.history.replaceState({}, "", `/captures?${listUrl}`)
  }, [listUrl])
  const selectClass =
    "h-9 rounded-md border bg-background px-3 text-sm shadow-xs focus-visible:outline-2 focus-visible:outline-ring"
  return (
    <main className="mx-auto min-h-svh max-w-[100rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-widest text-muted-foreground uppercase">
            Page acquisition
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            Captures
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Follow outcomes, understand rendering, and inspect acquisition
            evidence.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            onClick={() => navigate("/captures/pacing")}
          >
            Domain pacing
          </Button>
          <WindowPicker
            value={period}
            onChange={(value) => {
              setPeriod(value)
            }}
          />
        </div>
      </div>
      {data ? (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric
            label="Pages captured"
            value={number(data.counts.captured ?? 0)}
            detail={`${percent(data.counts.captured ?? 0, (data.counts.captured ?? 0) + (data.counts.failed ?? 0))} of completed results`}
          />
          <Metric
            label="HTTP-only successes"
            value={percent(data.paths.http ?? 0, data.counts.captured ?? 0)}
            detail={`${plural(data.paths.http ?? 0, "page")} without a browser attempt`}
          />
          <Metric
            label="Median / p95 duration"
            value={duration(data.median_duration_ms)}
            detail={`p95 ${duration(data.p95_duration_ms)}`}
          />
          <Metric
            label="Paid-tier uses"
            value={number(data.paid)}
            detail={`${duration(data.browser_seconds * 1000)} browser execution in total`}
          />
        </div>
      ) : (
        <div className="mt-6 rounded-xl border">
          <QueryMessage
            loading={overview.isLoading}
            error={overview.error}
            retry={() => void overview.refetch()}
          />
        </div>
      )}
      <CaptureAnalyticsPanel window={period} />
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="relative min-w-52 flex-1">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search captures"
            placeholder="Search hostname or capture ID"
            className="pl-9"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        <select
          aria-label="Capture outcome"
          className={selectClass}
          value={outcome}
          onChange={(event) => setOutcome(event.target.value)}
        >
          <option value="all">All outcomes</option>
          {Object.entries(outcomeLabels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="Acquisition path"
          className={selectClass}
          value={path}
          onChange={(event) => setPath(event.target.value)}
        >
          <option value="all">All acquisition paths</option>
          {Object.entries(pathLabels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {reason && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <span>Reason: {humanize(reason)}</span>
          <Button variant="ghost" size="sm" onClick={() => setReason("")}>
            Clear reason filter
          </Button>
        </div>
      )}
      <div className="mt-4 overflow-hidden rounded-xl border bg-card">
        <div className="hidden grid-cols-[1.3fr_.8fr_1fr_.55fr_.65fr] gap-4 border-b bg-muted/25 px-5 py-3 text-xs font-medium text-muted-foreground lg:grid">
          <span>Page / capture</span>
          <span>Outcome</span>
          <span>Acquisition path</span>
          <span className="text-right">Duration</span>
          <span className="text-right">Browser time</span>
        </div>
        {list.isLoading || list.isError ? (
          <QueryMessage
            loading={list.isLoading}
            error={list.error}
            retry={() => void list.refetch()}
          />
        ) : rows.length ? (
          <div className="divide-y">
            {rows.map((row) => (
              <button
                type="button"
                key={row.id}
                onClick={() => navigate(`/captures/${row.id}?${filterParams}`)}
                className="grid w-full gap-3 px-5 py-4 text-left hover:bg-muted/35 lg:grid-cols-[1.3fr_.8fr_1fr_.55fr_.65fr] lg:items-center"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {row.capture_hostname ?? "Capture"}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {new Date(row.created_at).toLocaleString()} ·{" "}
                    <span className="font-mono">{row.id.slice(0, 8)}</span>
                  </p>
                </div>
                <div>
                  <CaptureOutcome value={row.capture_outcome} />
                  {row.capture?.failure_code && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {humanize(row.capture.failure_code)}
                    </p>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">
                  {row.capture_path
                    ? pathLabels[row.capture_path]
                    : "No completed acquisition"}
                </p>
                <p className="text-sm tabular-nums lg:text-right">
                  <span className="text-xs text-muted-foreground lg:hidden">
                    Duration:{" "}
                  </span>
                  {row.capture
                    ? duration(row.capture.duration_ms)
                    : row.capture_outcome === "in_progress"
                      ? "In progress"
                      : "—"}
                </p>
                <p className="text-sm tabular-nums lg:text-right">
                  <span className="text-xs text-muted-foreground lg:hidden">
                    Browser:{" "}
                  </span>
                  {row.capture
                    ? duration(row.capture.browser_seconds * 1000)
                    : "—"}
                </p>
              </button>
            ))}
          </div>
        ) : (
          <div className="flex min-h-60 flex-col items-center justify-center p-6 text-center">
            <FileText className="size-7 text-muted-foreground" />
            <p className="mt-3 font-medium">No captures in this view</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Captures will appear here as pages are requested. Try a longer
              period or fewer filters.
            </p>
          </div>
        )}
        {list.hasNextPage && (
          <div className="border-t p-4 text-center">
            <Button
              variant="outline"
              disabled={list.isFetchingNextPage}
              onClick={() => void list.fetchNextPage()}
            >
              {list.isFetchingNextPage ? "Loading…" : "Load more captures"}
            </Button>
          </div>
        )}
      </div>
      <p className="mt-4 text-xs leading-5 text-muted-foreground">
        {plural(rows.length, "capture")} shown. Completed rows are selected by
        completion time; in-progress work uses request time. Overview numbers
        cover the whole period, independent of list filters.
      </p>
    </main>
  )
}

function AttemptStep({
  attempt,
  index,
}: {
  attempt: CaptureAttempt
  index: number
}) {
  return (
    <div className="flex gap-4 px-5 py-5">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-full border bg-muted/40 text-xs font-medium">
        {index + 1}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">
            {attempt.path === "http"
              ? "HTTP fetch"
              : attempt.tier === "managed"
                ? "Local browser render"
                : "Challenge resolution"}
          </h3>
          <span className="text-xs text-muted-foreground tabular-nums">
            {duration(attempt.duration_ms)}
            {attempt.status_code && ` · HTTP ${attempt.status_code}`}
          </span>
        </div>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {reasonLabels[attempt.reason]}
        </p>
        {attempt.assessment && (
          <p className="mt-2 text-xs">
            Assessment:{" "}
            <span className="text-muted-foreground">
              {humanize(attempt.assessment)}
            </span>
          </p>
        )}
        {attempt.http_coverage !== undefined && (
          <p className="mt-2 text-xs text-muted-foreground">
            HTTP contained {(attempt.http_coverage * 100).toFixed(0)}% of the
            compared rendered content.
            {attempt.http_sufficient
              ? " Confirmed sufficient."
              : " Not sufficient."}
          </p>
        )}
        <Badge variant="secondary" className="mt-3">
          {attempt.decision === "accept"
            ? "Accepted"
            : attempt.decision === "escalate"
              ? "Continue to next tier"
              : "Attempt failed"}
        </Badge>
      </div>
    </div>
  )
}

export function CaptureDetailView({
  sessionId,
  navigate,
}: {
  sessionId: string
  navigate: (href: string) => void
}) {
  const detail = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () =>
      fetchJson<SessionDetail>(
        `/v1/admin/sessions/${encodeURIComponent(sessionId)}`
      ),
    refetchInterval: 5_000,
  })
  const row = detail.data
  const capture = row?.capture
  return (
    <main className="mx-auto min-h-svh max-w-[100rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <Button
        variant="ghost"
        size="sm"
        className="-ml-2"
        onClick={() => navigate(`/captures${window.location.search}`)}
      >
        <ArrowLeft />
        All captures
      </Button>
      {detail.isLoading || detail.isError || !row ? (
        <div className="mt-5 rounded-xl border">
          <QueryMessage
            loading={detail.isLoading}
            error={detail.error}
            retry={() => void detail.refetch()}
          />
        </div>
      ) : row.workload !== "capture" ? (
        <div className="mt-5 rounded-xl border p-5">
          <p>This is an automation session.</p>
          <ViewLink
            label="Open session"
            href={`/sessions/${sessionId}`}
            navigate={navigate}
          />
        </div>
      ) : (
        <>
          <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
                {row.capture_hostname ?? "Page capture"}
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Requested {new Date(row.created_at).toLocaleString()}
              </p>
              <p className="mt-1 font-mono text-xs text-muted-foreground">
                {row.id}
              </p>
            </div>
            <CaptureOutcome value={row.capture_outcome} />
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Capture duration"
              value={
                capture
                  ? duration(capture.duration_ms)
                  : row.capture_outcome === "in_progress"
                    ? "In progress"
                    : "—"
              }
            />
            <Metric
              label="Acquisition path"
              value={row.capture_path ? pathLabels[row.capture_path] : "—"}
            />
            <Metric
              label="Browser execution"
              value={capture ? duration(capture.browser_seconds * 1000) : "—"}
            />
            <Metric
              label="Occupied capacity"
              value={duration(row.total_capacity_occupied_ms)}
              detail={`${number(row.modeled_cost_units)} modeled cost units · finalized attempts`}
            />
          </div>
          <div className="mt-5 grid gap-5 xl:grid-cols-[1.5fr_1fr]">
            <Section
              title="Acquisition timeline"
              description="What was tried and why the capture continued or finished"
            >
              {capture?.attempts.length ? (
                <div className="divide-y">
                  {capture.attempts.map((attempt, index) => (
                    <AttemptStep
                      key={`${index}-${attempt.tier}`}
                      attempt={attempt}
                      index={index}
                    />
                  ))}
                </div>
              ) : (
                <div className="p-5 text-sm leading-6 text-muted-foreground">
                  {row.capture_outcome === "in_progress"
                    ? "The capture is in progress. Its acquisition evidence will appear when it finishes."
                    : row.capture_outcome === "rejected"
                      ? "Capacity admission ended before page acquisition could complete."
                      : "No capture result was recorded. The session’s lifecycle evidence is available below."}
                </div>
              )}
            </Section>
            <div className="space-y-5">
              <Section title="Result">
                <div className="p-5">
                  {capture?.outcome === "captured" ? (
                    <>
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <CheckCircle2 className="size-4 text-emerald-600" />
                        Page acquired
                      </div>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">
                        {capture.representation === "response_body"
                          ? "Returned the original HTTP response body."
                          : "Returned the browser’s rendered HTML."}
                      </p>
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <CircleAlert className="size-4 text-amber-600" />
                        {outcomeLabels[row.capture_outcome ?? "unknown"]}
                      </div>
                      <p className="mt-3 text-sm text-muted-foreground capitalize">
                        {humanize(
                          capture?.failure_code ??
                            row.terminal_reason ??
                            "No terminal result yet"
                        )}
                      </p>
                      {capture?.failure_category && (
                        <p className="mt-2 text-xs text-muted-foreground capitalize">
                          {capture.failure_category} failure
                        </p>
                      )}
                    </>
                  )}
                  {capture && (
                    <dl className="mt-5 space-y-3 border-t pt-4 text-sm">
                      <div className="flex justify-between">
                        <dt className="text-muted-foreground">
                          Reported bytes
                        </dt>
                        <dd className="tabular-nums">
                          {number(capture.bytes)}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-muted-foreground">
                          Paid tier used
                        </dt>
                        <dd>{capture.paid ? "Yes" : "No"}</dd>
                      </div>
                    </dl>
                  )}
                </div>
              </Section>
              <Section title="Capacity and evidence">
                <div className="p-5">
                  <p className="text-sm leading-6 text-muted-foreground">
                    HTTP-only captures reserve a local slot too. Browser
                    execution measures rendering; occupied capacity measures the
                    slot held by the request.
                  </p>
                  <ViewLink
                    label="Session events"
                    href={`/activity?session_id=${row.id}`}
                    navigate={navigate}
                  />
                  <details className="mt-3 text-xs">
                    <summary className="cursor-pointer text-muted-foreground">
                      Provider attempts
                    </summary>
                    <div className="mt-3 space-y-3">
                      {row.attempts.map((attempt) => (
                        <div key={attempt.id} className="rounded-md border p-3">
                          <p className="font-medium">
                            {attempt.provider === "browserless"
                              ? "Local browser capacity"
                              : "Browserless cloud"}
                          </p>
                          <p className="mt-1 text-muted-foreground capitalize">
                            {humanize(attempt.state)} ·{" "}
                            {duration(attempt.capacity_occupied_ms)} occupied
                          </p>
                          <p className="mt-1 font-mono text-muted-foreground">
                            {attempt.id}
                          </p>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              </Section>
            </div>
          </div>
        </>
      )}
    </main>
  )
}

export function CapturesPage({
  sessionId,
  navigate,
}: {
  sessionId?: string
  navigate: (href: string) => void
}) {
  return sessionId ? (
    <CaptureDetailView sessionId={sessionId} navigate={navigate} />
  ) : (
    <CaptureList navigate={navigate} />
  )
}
