# Downstream client examples

These programs are clients using Stolosio through Playwright's standard CDP API. They
are executable examples and the end-to-end acceptance targets for `/v1/connect`.

Set `STOLOSIO_CDP_URL` to the Stolosio WebSocket endpoint. Without a provider override
Stolosio uses the local Browserless fleet; name `browserless_cloud` for the paid cloud:

```bash
export STOLOSIO_CDP_URL='ws://localhost:8411/v1/connect'
export STOLOSIO_CDP_URL='ws://localhost:8411/v1/connect?stolosio.provider.slug=browserless_cloud'
```

Run each example from the repository root:

```bash
uv run python examples/01_goto_and_content.py
uv run python examples/02_interaction.py
uv run python examples/03_evaluate.py
uv run python examples/04_debug_stream.py
```

The examples use only the standard Playwright client. Switching providers requires
changing only `STOLOSIO_CDP_URL`.

## Targets

- `01_goto_and_content.py` navigates and reads the page content.
- `02_interaction.py` clicks a link and waits for the next page.
- `03_evaluate.py` evaluates JavaScript through the CDP connection.
- `04_debug_stream.py` shows an opt-in client reference and the separate, read-only
  DEBUG WebSocket alongside an ordinary Playwright CDP connection. Set
  `STOLOSIO_DEBUG_URL` when it isn't available at `ws://localhost:8411/v1/debug`.

The Docker E2E suite runs these same files, so a command that succeeds for a developer
is the exact downstream workflow exercised by automated acceptance.

For a single page, prefer `POST /v1/capture` (see [docs/CAPTURE.md](../docs/CAPTURE.md)):
it chooses the capture method itself and returns the exact document.
