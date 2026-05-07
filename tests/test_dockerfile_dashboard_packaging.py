from pathlib import Path


def test_dockerfile_builds_and_copies_dashboard_dist():
    dockerfile = Path("Dockerfile").read_text()

    assert "AS dashboard-build" in dockerfile
    assert "pnpm build" in dockerfile
    assert "COPY --from=dashboard-build /app/dashboard/dist /app/dashboard/dist" in dockerfile
