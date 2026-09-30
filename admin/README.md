# Stolosio admin

The operator interface for fleets, capacity, network and cost policy, sessions and observations.
This is separate from the public marketing/documentation site. It has no built-in
authentication; deploy behind your trusted access layer.

```sh
npm ci
npm run dev
npm run lint
npm run typecheck
npm run build
```

The package and container are named `stolosio-admin`. The container serves on port
8080 and proxies administrative API requests to `STOLOSIO_API_PROXY_TARGET`.
Its proxy deliberately blocks `/v1/connect`; automation uses the API Service.
