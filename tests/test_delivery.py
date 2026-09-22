from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_dockerfile_runs_non_root_with_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim-bookworm" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "http://127.0.0.1:8000/health" in dockerfile
    assert 'CMD ["python", "-m", "uvicorn"' in dockerfile


def test_docker_context_excludes_secrets_and_local_state() -> None:
    ignored = set(
        (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )

    assert {".env", ".git", ".cache", ".mamba", ".venv"} <= ignored


def test_compose_defaults_to_offline_hardened_runtime() -> None:
    compose = yaml.safe_load(
        (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    service = compose["services"]["api"]

    assert service["environment"]["AGENT_PROVIDER"] == "${AGENT_PROVIDER:-mock}"
    assert service["environment"]["AGENT_PLANNER"] == "${AGENT_PLANNER:-rule}"
    assert service["read_only"] is True
    assert service["init"] is True
    assert "no-new-privileges:true" in service["security_opt"]
    assert "model-cache:/app/.cache" in service["volumes"]


def test_ci_actions_are_sha_pinned_and_permissions_are_read_only() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    action_references = re.findall(r"uses:\s+([^\s#]+)", workflow_text)

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["quality"]["strategy"]["matrix"][
        "python-version"
    ] == ["3.10", "3.11", "3.12"]
    assert action_references
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_references)
    assert "persist-credentials: false" in workflow_text
    assert "--cov-fail-under=85" in workflow_text
    assert "docker build --tag location-aware-travel-agent:ci ." in workflow_text
