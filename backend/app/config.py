from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("RC_DATA_DIR", str(ROOT / "data"))).resolve())
    import_roots: list[Path] = field(default_factory=lambda: [Path(p.strip()).resolve() for p in os.getenv("RC_IMPORT_ROOTS", str(ROOT / "samples")).split(",") if p.strip()])
    ollama_url: str = field(default_factory=lambda: os.getenv("RC_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"))
    ollama_model: str = field(default_factory=lambda: os.getenv("RC_OLLAMA_MODEL", ""))
    docker_image: str = field(default_factory=lambda: os.getenv("RC_DOCKER_IMAGE", "rootcause-runner:local"))
    test_timeout: int = field(default_factory=lambda: int(os.getenv("RC_TEST_TIMEOUT", "120")))
    ai_timeout: int = field(default_factory=lambda: int(os.getenv("RC_AI_TIMEOUT", "180")))
    enable_trusted_demo_runner: bool = field(default_factory=lambda: os.getenv("RC_ENABLE_TRUSTED_DEMO_RUNNER", "false").strip().lower() in {"1", "true", "yes"})

    def __post_init__(self) -> None:
        parsed = urlparse(self.ollama_url)
        # This release intentionally supports local inference only. No accidental cloud egress.
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("RC_OLLAMA_URL must be a loopback HTTP endpoint without credentials")
        if not 1 <= self.ai_timeout <= 900:
            raise ValueError("RC_AI_TIMEOUT must be between 1 and 900 seconds")

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def investigations_dir(self) -> Path:
        return self.data_dir / "investigations"
