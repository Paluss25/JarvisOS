from pathlib import Path


def test_jarvios_mounts_garmin_fit_source_readonly():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "/mnt/Brains/Sport:/mnt/Brains/Sport:ro" in compose
    assert "/mnt/Brains/Sport:/app/sport-docs:ro" in compose
    assert "/mnt/Brains/Sport:/app/sport-docs:rw" not in compose
