import { useQuery } from "@tanstack/react-query"
import { CircleDot, FileText, RefreshCw } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Metric,
  OutcomesChart,
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
import type {
  GatewayFleetSnapshot,
  OverviewWindow,
  ProviderFleetSnapshot,
  WorkloadOverview,
} from "@/types/api"

function Failures({
  data,
  href,
  navigate,
}: {
  data: WorkloadOverview
  href: string
  navigate: (href: string) => void
}) {
  return (
    <div className="mt-5 border-t pt-4">
      <p className="mb-2 text-xs font-medium text-muted-foreground">
        Most frequent failures and interruptions
      </p>
      {data.failures.length ? (
        <div className="space-y-1">
          {data.failures.map((row) => (
            <button
              key={row.reason}
              type="button"
              onClick={() =>
                navigate(`${href}&reason=${encodeURIComponent(row.reason)}`)
              }
              className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted/50"
            >
              <span className="capitalize">{humanize(row.reason)}</span>
              <span className="text-muted-foreground tabular-nums">
                {number(row.count)}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="py-2 text-sm text-muted-foreground">
          No failures recorded in this period.
        </p>
      )}
    </div>
  )
}

export function OverviewPage({
  navigate,
}: {
  navigate: (href: string) => void
}) {
  const [window, setWindow] = useState<OverviewWindow>("24h")
  const overview = useOverview(window)
  const fleet = useQuery({
    queryKey: ["overview-fleet"],
    queryFn: () => fetchJson<ProviderFleetSnapshot[]>("/v1/fleet/providers"),
    refetchInterval: 10_000,
  })
  const gateway = useQuery({
    queryKey: ["overview-gateway"],
    queryFn: () => fetchJson<GatewayFleetSnapshot>("/v1/fleet/gateway"),
    refetchInterval: 10_000,
  })
  const automation = overview.data?.automation
  const capture = overview.data?.capture
  const captureSuccess = capture?.counts.captured ?? 0
  const captureFailures = capture?.counts.failed ?? 0
  const sessionClosed = automation?.counts.closed ?? 0
  const sessionFailed = automation?.counts.failed ?? 0
  const capturesHref = `/captures?window=${window}`
  const sessionsHref = `/sessions?window=${window}`
  return (
    <main className="mx-auto min-h-svh max-w-[100rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-widest text-muted-foreground uppercase">
            Stolosio console
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            Overview
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Browser automation and page capture, at a glance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <WindowPicker value={window} onChange={setWindow} />
          <Button
            variant="outline"
            size="icon"
            aria-label="Refresh overview"
            onClick={() => {
              void overview.refetch()
              void fleet.refetch()
              void gateway.refetch()
            }}
          >
            <RefreshCw className={overview.isFetching ? "animate-spin" : ""} />
          </Button>
        </div>
      </div>

      {overview.isLoading || overview.isError || !automation || !capture ? (
        <div className="mt-6 rounded-xl border bg-card">
          <QueryMessage
            loading={overview.isLoading}
            error={overview.error}
            retry={() => void overview.refetch()}
          />
        </div>
      ) : (
        <div className="mt-6 grid items-start gap-5 xl:grid-cols-2">
          <Section
            title="Automation sessions"
            description="CDP and Playwright connections"
            action={
              <ViewLink
                label="Sessions"
                href={sessionsHref}
                navigate={navigate}
              />
            }
          >
            <div className="p-5">
              <div className="mb-5 flex items-center gap-2 text-xs text-muted-foreground">
                <CircleDot className="size-4" />
                <span>{number(automation.active)} in progress now</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Metric
                  label="Sessions closed"
                  value={number(sessionClosed)}
                  detail={`${percent(sessionClosed, sessionClosed + sessionFailed)} closed normally`}
                  href={`${sessionsHref}&state=closed`}
                  navigate={navigate}
                />
                <Metric
                  label="Sessions failed"
                  value={number(sessionFailed)}
                  detail="Connection or lifecycle failure"
                  href={`${sessionsHref}&state=failed`}
                  navigate={navigate}
                />
                <Metric
                  label="Median session length"
                  value={duration(automation.median_duration_ms)}
                  detail={`p95 ${duration(automation.p95_duration_ms)}`}
                />
                <Metric
                  label="Browser connected"
                  value={duration(automation.browser_ms)}
                  detail={`${duration(automation.capacity_ms)} capacity occupied`}
                />
              </div>
              <div className="mt-5">
                <OutcomesChart series={automation.series} />
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3 border-t pt-4">
                <div>
                  <p className="text-xs text-muted-foreground">Commands</p>
                  <p className="mt-1 font-medium tabular-nums">
                    {number(automation.command_count)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">
                    Failed / interrupted
                  </p>
                  <p className="mt-1 font-medium tabular-nums">
                    {number(automation.failed_commands)} /{" "}
                    {number(automation.interrupted_commands)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">
                    Mean command duration
                  </p>
                  <p className="mt-1 font-medium tabular-nums">
                    {duration(automation.mean_command_ms)}
                  </p>
                </div>
              </div>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                Normal closure describes the connection, not the success of the
                caller’s task. Command totals reflect retained summaries
                received in this period.
              </p>
              <Failures
                data={automation}
                href={`${sessionsHref}&state=failed`}
                navigate={navigate}
              />
            </div>
          </Section>
          <Section
            title="Page captures"
            description="HTTP acquisition, rendering, and challenge resolution"
            action={
              <ViewLink
                label="Captures"
                href={capturesHref}
                navigate={navigate}
              />
            }
          >
            <div className="p-5">
              <div className="mb-5 flex items-center gap-2 text-xs text-muted-foreground">
                <FileText className="size-4" />
                <span>{number(capture.active)} in progress now</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Metric
                  label="Pages captured"
                  value={number(captureSuccess)}
                  detail={`${percent(captureSuccess, captureSuccess + captureFailures)} of completed capture results`}
                  href={`${capturesHref}&outcome=captured`}
                  navigate={navigate}
                />
                <Metric
                  label="HTTP-only successes"
                  value={percent(capture.paths.http ?? 0, captureSuccess)}
                  detail={`${plural(capture.paths.http ?? 0, "page")} acquired without rendering`}
                  href={`${capturesHref}&outcome=captured&path=http`}
                  navigate={navigate}
                />
                <Metric
                  label="Median capture time"
                  value={duration(capture.median_duration_ms)}
                  detail={`p95 ${duration(capture.p95_duration_ms)}`}
                />
                <Metric
                  label="Browser execution"
                  value={duration(capture.browser_seconds * 1000)}
                  detail={`${duration(capture.capacity_ms)} capacity occupied`}
                />
              </div>
              <div className="mt-5">
                <OutcomesChart series={capture.series} />
              </div>
              <div className="mt-5 space-y-3 border-t pt-4">
                {Object.entries(pathLabels).map(([path, label]) => (
                  <button
                    type="button"
                    key={path}
                    onClick={() =>
                      navigate(`${capturesHref}&outcome=captured&path=${path}`)
                    }
                    className="block w-full rounded-md text-left hover:bg-muted/40"
                  >
                    <div className="flex justify-between text-xs">
                      <span>{label}</span>
                      <span className="text-muted-foreground tabular-nums">
                        {number(capture.paths[path] ?? 0)} ·{" "}
                        {percent(capture.paths[path] ?? 0, captureSuccess)}
                      </span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary/65"
                        style={{
                          width: `${captureSuccess ? (100 * (capture.paths[path] ?? 0)) / captureSuccess : 0}%`,
                        }}
                      />
                    </div>
                  </button>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <button
                  className="hover:underline"
                  onClick={() => navigate(`${capturesHref}&outcome=failed`)}
                >
                  {plural(captureFailures, "failed result")}
                </button>
                <button
                  className="hover:underline"
                  onClick={() => navigate(`${capturesHref}&outcome=rejected`)}
                >
                  {plural(capture.counts.rejected ?? 0, "recorded rejection")}
                </button>
                <span>{plural(capture.paid, "paid-tier use")}</span>
              </div>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                Paths describe work performed, including verification renders.
                HTTP-only captures still reserve local browser capacity.
              </p>
              <Failures
                data={capture}
                href={capturesHref}
                navigate={navigate}
              />
            </div>
          </Section>
        </div>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-[1.5fr_1fr]">
        <Section
          title="Shared capacity"
          description="Live intake, provider queues, and ready instances"
          action={
            <ViewLink label="Capacity" href="/fleets" navigate={navigate} />
          }
        >
          {fleet.isLoading || gateway.isLoading ? (
            <QueryMessage loading />
          ) : fleet.isError || gateway.isError ? (
            <QueryMessage
              error={fleet.error ?? gateway.error}
              retry={() => {
                void fleet.refetch()
                void gateway.refetch()
              }}
            />
          ) : (
            <>
              <div className="flex items-center justify-between border-b px-5 py-4 text-sm">
                <span>Global session slots</span>
                <span className="font-medium tabular-nums">
                  {number(gateway.data?.active_sessions ?? 0)} /{" "}
                  {number(gateway.data?.capacity ?? 0)} occupied
                </span>
              </div>
              {fleet.data?.length ? (
                fleet.data.map((provider) => (
                  <button
                    type="button"
                    key={provider.provider}
                    onClick={() => navigate(`/fleets/${provider.provider}`)}
                    className="flex w-full flex-wrap items-center justify-between gap-3 border-b px-5 py-4 text-left text-sm last:border-0 hover:bg-muted/40"
                  >
                    <div>
                      <p className="font-medium">
                        {provider.provider === "browserless"
                          ? "Local browsers"
                          : "Browserless cloud"}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {provider.provider === "browserless"
                          ? `${provider.ready_instances} ready · ${provider.draining_instances} draining · ${provider.unhealthy_instances} unhealthy`
                          : "External concurrency limit"}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="tabular-nums">
                        {provider.active_attempts} / {provider.capacity}{" "}
                        occupied
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {provider.queued_attempts} queued
                        {provider.queued_attempts > 0 &&
                          ` · oldest ${duration(provider.oldest_queued_attempt_seconds * 1000)}`}
                      </p>
                    </div>
                  </button>
                ))
              ) : (
                <p className="p-5 text-sm text-muted-foreground">
                  No provider capacity has been configured.
                </p>
              )}
            </>
          )}
        </Section>
        <Section
          title="Usage"
          description="Modeled resource cost for completed work"
          action={
            <ViewLink label="Usage report" href="/cost" navigate={navigate} />
          }
        >
          {overview.data ? (
            <div className="p-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">Automation</p>
                  <p className="mt-2 text-xl font-semibold tabular-nums">
                    {number(overview.data.automation.modeled_cost_units)}{" "}
                    <span className="text-xs font-normal text-muted-foreground">
                      units
                    </span>
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Captures</p>
                  <p className="mt-2 text-xl font-semibold tabular-nums">
                    {number(overview.data.capture.modeled_cost_units)}{" "}
                    <span className="text-xs font-normal text-muted-foreground">
                      units
                    </span>
                  </p>
                </div>
              </div>
              <p className="mt-5 text-sm leading-6 text-muted-foreground">
                Cost uses configured rates and occupied capacity. It is an
                estimate, not a provider invoice.
              </p>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                Historical totals use completion time. Active counts are live.
                Captures rejected before a database transaction commits appear
                only in operational metrics.
              </p>
            </div>
          ) : (
            <QueryMessage loading={overview.isLoading} error={overview.error} />
          )}
        </Section>
      </div>
    </main>
  )
}
