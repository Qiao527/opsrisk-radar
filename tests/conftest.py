from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from opsrisk.database import Database

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def mock_transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    """Serve fixed responses by URL; anything else is a 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handler)


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary working directory with the real config, as the CLI expects."""
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    monkeypatch.chdir(tmp_path)
    return tmp_path
