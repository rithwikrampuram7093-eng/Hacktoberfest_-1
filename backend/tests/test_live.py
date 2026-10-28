"""Opt-in REAL runtime checks. No substitute model or Docker results are used here.

RC_RUN_LIVE=1 .venv/Scripts/python.exe -m pytest backend/tests/test_live.py -q
This checks the failing demo and real model proposal; developer approval remains manual.
"""
import os
from uuid import uuid4

import pytest

from app.config import ROOT, Settings
from app.database import Store
from app.intake import import_directory
from app.providers import OllamaProvider
from app.sandbox import DockerSandbox
from app.workflow import Workflow

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.getenv("RC_RUN_LIVE") != "1", reason="Opt-in live Docker/Ollama integration; unavailable runtimes are never simulated")]


async def test_real_demo_failure_and_ai_patch_proposal(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    provider = OllamaProvider(settings)
    sandbox = DockerSandbox(settings.docker_image, settings.test_timeout)
    assert (await provider.health())["available"], "Install a local Gemma model before enabling the live suite"
    assert (await sandbox.health())["available"], "Docker and the trusted local runner image are required"
    store = Store(settings.data_dir)
    project_id, identity = uuid4().hex, uuid4().hex
    metadata = import_directory(ROOT / "samples/order-service", settings.projects_dir / project_id / "source", [ROOT / "samples"])
    project = store.add_project(project_id, metadata["name"], metadata["file_count"])
    store.create(identity, project)
    workflow = Workflow(settings, store, provider, sandbox)
    await workflow.investigate(identity, "")
    item = store.get(identity)
    assert item["baseline"]["status"] == "failed", item
    assert item["baseline"]["failed"] > 0 and item["baseline"]["passed"] > 0
    assert item["status"] == "awaiting_approval", item
    assert item["hypotheses"] and item["patch"]["diff"]
    assert item["verification"] is None
    assert not workflow.workspace(identity).parent.joinpath("candidate").exists()
