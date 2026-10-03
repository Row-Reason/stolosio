from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.admin_overview import router


class Queries:
    async def overview(self, window):
        self.window = window
        common = {
            "active": 0,
            "counts": {},
            "median_duration_ms": None,
            "p95_duration_ms": None,
            "capacity_ms": 0,
            "browser_ms": 0,
            "modeled_cost_units": 0,
            "series": [],
            "failures": [],
        }
        return {
            "window": window,
            "starts_at": "2026-10-01T00:00:00Z",
            "ends_at": "2026-10-02T00:00:00Z",
            "automation": {
                **common,
                "command_count": 0,
                "failed_commands": 0,
                "interrupted_commands": 0,
                "mean_command_ms": None,
            },
            "capture": {**common, "paths": {}, "browser_seconds": 0, "paid": 0},
        }


def test_overview_validates_windows_and_returns_both_workloads():
    app = FastAPI()
    queries = Queries()
    app.state.workload_queries = queries
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/v1/admin/overview?window=7d")
    assert response.status_code == 200
    assert queries.window == "7d"
    assert response.json()["automation"]["active"] == response.json()["capture"]["active"] == 0
    assert client.get("/v1/admin/overview?window=forever").status_code == 422
