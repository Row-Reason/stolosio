import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"
import { toast } from "sonner"
import { DomainPacingPage } from "@/components/domain-pacing-page"
import type { PacingDashboard } from "@/types/api"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const response: PacingDashboard = {
  window: "1h",
  starts_at: "2026-10-04T10:00:00Z",
  ends_at: "2026-10-04T11:00:00Z",
  tracking_since: null,
  bucket_seconds: 60,
  domains_truncated: false,
  settings: {
    version: 1,
    default_concurrency: 2,
    default_spacing_seconds: 1,
    maximum_concurrency: 8,
    minimum_spacing_seconds: 0.1,
    maximum_spacing_seconds: 60,
    learned_ttl_seconds: 86400,
    healthy_samples: 20,
    overload_samples: 3,
    cooldown_seconds: 30,
  },
  domains: [
    {
      hostname: "en.wikipedia.org",
      concurrency: 5,
      spacing_seconds: 0.15,
      expires_at: "2026-10-05T11:00:00Z",
      cooldown_until: null,
      healthy_samples: 0,
      concurrency_samples: 0,
      overload_samples: 0,
      generation: 21,
      reason: "healthy_at_limit",
      adjusted_at: "2026-10-04T10:59:00Z",
      expired: false,
      reset_requested: false,
      effective_concurrency: 5,
      effective_spacing_seconds: 0.15,
      active_captures: 2,
      traffic: {
        offered: 14400,
        admitted: 12960,
        refusals: {
          domain_spacing: 0,
          domain_concurrency: 0,
          domain_cooldown: 0,
        },
      },
      offered_per_second: 4,
      admitted_per_second: 3.6,
    },
  ],
  totals: {
    offered: 14400,
    admitted: 12960,
    refusals: {},
    origin_throttled: 0,
    origin_overload: 0,
    mean_capture_seconds: 0.4,
    active_hosts: 1,
    cooldown_hosts: 0,
    throttled_hosts: 0,
  },
  series: [],
  history: [
    {
      at: "2026-10-04T10:59:00Z",
      hostname: "en.wikipedia.org",
      concurrency: 5,
      spacing_seconds: 0.15,
      generation: 21,
      reason: "healthy_at_limit",
    },
  ],
}

function mount(hostname?: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const navigate = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <DomainPacingPage hostname={hostname} navigate={navigate} />
    </QueryClientProvider>
  )
  return navigate
}

it("distinguishes allowance from exercised demand and opens host details", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(response))
  )
  const navigate = mount()
  const host = await screen.findByRole("button", { name: "en.wikipedia.org" })
  expect(screen.getByText("Demand below allowance")).toBeTruthy()
  expect(screen.getByText("2 / 5")).toBeTruthy()
  await userEvent.click(host)
  expect(navigate).toHaveBeenCalledWith("/captures/pacing/en.wikipedia.org")
  await userEvent.type(
    screen.getByRole("textbox", { name: "Filter hostnames" }),
    "absent"
  )
  expect(screen.getByText(/No matching hosts/)).toBeTruthy()
})

it("shows adjustment history, honest missing measurements, and surfaces reset errors", async () => {
  const fetch = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === "POST"
      ? Response.json({ detail: "Reset unavailable" }, { status: 503 })
      : Response.json(response)
  )
  vi.stubGlobal("fetch", fetch)
  mount("en.wikipedia.org")
  await screen.findByText("Occupied / allowed now")
  expect(screen.getByText(/reduces spacing by 20%/)).toBeTruthy()
  expect(screen.getByText("Healthy responses near allowance")).toBeTruthy()
  expect(
    screen.getByText(/Traffic measurement starts with the next capture/)
  ).toBeTruthy()
  expect(
    screen
      .getByRole("progressbar", { name: "Healthy qualifying samples" })
      .getAttribute("value")
  ).toBe("0")
  await userEvent.click(
    screen.getByRole("button", { name: "Reset learned allowance" })
  )
  expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  )
  await userEvent.click(screen.getByRole("button", { name: "Confirm reset" }))
  expect(toast.error).toHaveBeenCalledWith("Reset unavailable")
})
