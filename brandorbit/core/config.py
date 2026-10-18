"""Runtime configuration from environment variables (never from committed files)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("BRANDORBIT_DB", ROOT / "brandorbit.db")))
    data_dir: Path = ROOT / "data"
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
    request_timeout_s: float = float(os.getenv("BRANDORBIT_TIMEOUT_S", "45"))
    max_retries: int = int(os.getenv("BRANDORBIT_MAX_RETRIES", "2"))
    max_prompts_per_run: int = int(os.getenv("BRANDORBIT_MAX_PROMPTS_PER_RUN", "25"))
    max_calls_per_run: int = int(os.getenv("BRANDORBIT_MAX_CALLS_PER_RUN", "60"))
    allow_website_fetch: bool = os.getenv("BRANDORBIT_ALLOW_WEBSITE_FETCH", "false").lower() == "true"
    max_upload_bytes: int = 2 * 1024 * 1024

    @property
    def live_providers(self) -> list[str]:
        out = []
        if self.openai_api_key:
            out.append("openai")
        if self.anthropic_api_key:
            out.append("anthropic")
        return out

    @property
    def demo_mode(self) -> bool:
        return not self.live_providers


def get_settings() -> Settings:
    return Settings()
