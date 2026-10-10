# CI and releases

GitHub Actions provides two paths:

- `CI` applies migrations to PostgreSQL, runs backend lint and tests with
  JetStream-enabled NATS, runs frontend lint/type-check/build, builds all five containers,
  and validates the Helm/Kubernetes manifests on pull requests and pushes to `main`.
- `Gateway and capture smoke` exercises CDP, capture, and capacity cleanup against a
  Docker-only origin, without external websites or paid providers. Backend CI requires
  PostgreSQL and NATS; unavailable services fail instead of skipping coverage.
- `Publish` builds backend/admin images for `linux/amd64` and `linux/arm64`, and
  the public-site image for `linux/amd64` only. It pushes them to GHCR on `main`,
  semantic version tags, and manual runs.

The published Stolosio artifacts are:

```text
ghcr.io/row-reason/stolosio
ghcr.io/row-reason/stolosio-admin
ghcr.io/row-reason/stolosio-public
ghcr.io/row-reason/stolosio-browserless
ghcr.io/row-reason/stolosio-fetch-proxy
oci://ghcr.io/row-reason/charts/stolosio (future tagged releases)
```

The first image is shared by the API, workers, migration Job, and fleet controller.
The matching `stolosio-browserless` and `stolosio-fetch-proxy` images supply the
mandatory page-fetch isolation described in [Network policy](NETWORK_POLICY.md). PostgreSQL and
NATS are external services, not Stolosio images.

The public image serves only static marketing and documentation pages on port 8080.
Deployment manifests, ingress, DNS, and TLS belong in the infrastructure repository.
This repository supplies the image and its runtime contract. CI validates builds on pull
requests; Publish runs separately on main, tags, and manual dispatch. Require CI
before merging. Each public-image build also runs its own site checks.

## Tags

A `main` build publishes `main` and `sha-<short-commit>` image tags. A tag such as
`v0.1.15` publishes image tags `0.1.15`, `0.1`, `sha-<short-commit>`, and `latest`, then
publishes the Helm chart as OCI version `0.1.15`. Pre-release tags do not move `latest`.
A manual run always publishes the immutable commit tag and may also publish its branch
tag.

The chart is only published for a Git tag. The workflow requires the Git tag without
its `v` prefix, the Python project version, `charts/stolosio/Chart.yaml` `version` and
`appVersion`, and the chart's default Stolosio image tags to match. This check runs
before any release image is pushed.

To release `0.1.15` after CI passes:

```bash
git tag v0.1.15
git push origin v0.1.15
```

GitHub's repository `GITHUB_TOKEN` publishes all artifacts; no long-lived publishing
credential is required. New packages follow the repository/package visibility
configuration. Company images are private; operators need a classic personal access
token with `read:packages` and a corresponding image-pull Secret. Do not change
package visibility as part of namespace retirement.

Enable all `CI` checks as required checks on the default branch before treating a
release as supported. GitHub Actions dependencies are commit-pinned and Dependabot is
configured to propose their updates.

## Experimental release policy

Current versions are experimental and do not promise API or database compatibility.
Document breaking changes in release notes. Before declaring a deployment supported,
stop rewriting its applied migrations and provide forward migrations for retained data.
A public repository alone does not make a release production-supported.

Before making the repository public, review dependency licenses and redistribution notices, enable private vulnerability
reporting, and review Git history and published
artifacts for secrets or private data. Automated scans supplement that review.

Version 0.1.15 names the operator UI `stolosio-admin`. Helm values are
`admin` and `adminImage`; the source directory is `admin/`. The former web package
is retired. Use 0.1.15 or a pinned newer Git chart with matching images.

## Company namespace handover

The running company deployment uses the image commit `sha-49018a7` (the public
site uses `sha-c25b219`). The chart defaults use that available company image
commit; they do not imply that a `0.1.15` company release exists. A future version
release must update the default image tags together with all versions checked by
Publish. Company IaC supplies explicit digest pins and private-registry credentials.

The historical `elei-io/charts/stolosio` chart has not been copied to Row-Reason.
The OCI install examples and `deploy/flux/source.yaml` still target that retained
legacy chart and are not the company deployment procedure. Those older published
charts embed old image defaults: override all four image repositories and tags
with company pins before using them after legacy image retirement. The company
cluster uses the chart from its own IaC tree.
