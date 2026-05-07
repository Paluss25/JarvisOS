from pathlib import Path


def test_dockerfile_copies_plugins_directory():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "COPY plugins/ ./plugins/" in dockerfile
    assert "COPY src/ ./src/" in dockerfile
    assert "COPY vendor/mailctl /tmp/mailctl" in dockerfile
    assert "COPY html-text-cli /tmp/html-text-cli" in dockerfile
