import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { apiRequest, extractApiError } from "@/lib/api"
import type { DomainPacingSettings } from "@/types/api"

type SettingsValues = Omit<DomainPacingSettings, "version">

const fields: {
  key: keyof SettingsValues
  label: string
  min: number
  max: number
  step: number
}[] = [
  {
    key: "default_concurrency",
    label: "Starting concurrency",
    min: 1,
    max: 100,
    step: 1,
  },
  {
    key: "default_spacing_seconds",
    label: "Starting spacing (seconds)",
    min: 0.01,
    max: 60,
    step: 0.01,
  },
  {
    key: "maximum_concurrency",
    label: "Maximum concurrency",
    min: 1,
    max: 100,
    step: 1,
  },
  {
    key: "minimum_spacing_seconds",
    label: "Minimum spacing (seconds)",
    min: 0.01,
    max: 60,
    step: 0.01,
  },
  {
    key: "maximum_spacing_seconds",
    label: "Maximum spacing (seconds)",
    min: 0.01,
    max: 3600,
    step: 0.01,
  },
  {
    key: "learned_ttl_seconds",
    label: "Learned limit TTL (seconds)",
    min: 60,
    max: 2592000,
    step: 1,
  },
  {
    key: "healthy_samples",
    label: "Healthy samples before increasing",
    min: 2,
    max: 1000,
    step: 1,
  },
  {
    key: "overload_samples",
    label: "Overload samples before backing off",
    min: 2,
    max: 100,
    step: 1,
  },
  {
    key: "cooldown_seconds",
    label: "Default cooldown (seconds)",
    min: 1,
    max: 3600,
    step: 1,
  },
]

function SettingsForm({ settings }: { settings: DomainPacingSettings }) {
  const queryClient = useQueryClient()
  const [values, setValues] = useState<SettingsValues>(() => {
    return Object.fromEntries(
      fields.map(({ key }) => [key, settings[key]])
    ) as SettingsValues
  })
  const mutation = useMutation({
    mutationFn: (values: SettingsValues) =>
      apiRequest<DomainPacingSettings>("/v1/admin/domain-pacing/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      }),
    onSuccess: (value) => {
      queryClient.setQueryData(["domain-pacing-settings"], value)
      void queryClient.invalidateQueries({ queryKey: ["domain-pacing-states"] })
      void queryClient.invalidateQueries({ queryKey: ["pacing-dashboard"] })
      toast.success("Domain pacing settings updated")
    },
    onError: (error) => toast.error(extractApiError(error)),
  })
  const valid =
    values.default_concurrency <= values.maximum_concurrency &&
    values.minimum_spacing_seconds <= values.default_spacing_seconds &&
    values.default_spacing_seconds <= values.maximum_spacing_seconds &&
    fields.every(
      ({ key, min, max, step }) =>
        Number.isFinite(values[key]) &&
        values[key] >= min &&
        values[key] <= max &&
        (step !== 1 || Number.isInteger(values[key]))
    )
  const dirty = fields.some(({ key }) => values[key] !== settings[key])
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (valid && dirty) mutation.mutate(values)
  }
  return (
    <form onSubmit={submit} className="space-y-4 p-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {fields.map(({ key, label, min, max, step }) => (
          <div key={key} className="space-y-2">
            <Label htmlFor={`pacing-${key}`}>{label}</Label>
            <Input
              id={`pacing-${key}`}
              type="number"
              min={min}
              max={max}
              step={step}
              required
              value={Number.isNaN(values[key]) ? "" : values[key]}
              onChange={(event) =>
                setValues({ ...values, [key]: event.target.valueAsNumber })
              }
            />
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Changes reset learned limits on the next admission. Active captures and
        cooldowns are preserved.
      </p>
      {!valid && (
        <p className="text-sm text-destructive">
          Starting limits must be within the configured bounds.
        </p>
      )}
      <Button type="submit" disabled={!dirty || !valid || mutation.isPending}>
        Save pacing settings
      </Button>
    </form>
  )
}

export function DomainPacingSettingsPanel() {
  const settings = useQuery({
    queryKey: ["domain-pacing-settings"],
    queryFn: () =>
      apiRequest<DomainPacingSettings>("/v1/admin/domain-pacing/settings"),
  })
  return (
    <Card className="gap-0 rounded-lg">
      <div className="border-b px-4 py-3">
        <h2 className="font-semibold">Domain pacing</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Shared capture limits per hostname. Limits adapt to healthy traffic
          and target throttling. Each capture can make several HTTP and browser
          requests.
        </p>
        <a
          className="mt-3 inline-block text-sm text-primary underline"
          href="/captures/pacing"
        >
          Inspect domain traffic and learned allowances →
        </a>
      </div>
      {settings.isPending ? (
        <p className="p-4 text-sm">Loading pacing settings…</p>
      ) : settings.error ? (
        <p role="alert" className="p-4 text-sm text-destructive">
          {extractApiError(settings.error)}
        </p>
      ) : (
        settings.data && (
          <SettingsForm key={settings.data.version} settings={settings.data} />
        )
      )}
    </Card>
  )
}
