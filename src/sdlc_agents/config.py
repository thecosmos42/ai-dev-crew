"""Application settings for the SDLC automation suite."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and YAML files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "anthropic"
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_temperature: float = 0.0
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    sdlc_db_path: Path = Path("metrics.db")
    prompt_version: str = "v1"
    max_tool_iterations: int = Field(default=8, ge=1)
    max_hitl_rounds: int = Field(default=2, ge=0)
    max_schema_retries: int = Field(default=2, ge=0)
    runs_dir: Path = Path("runs")
    standards_path: Path = Path("config/standards.yaml")
    pricing_path: Path = Path("config/pricing.yaml")

    def load_yaml(self, path: Path | None = None) -> dict[str, Any]:
        """Load a YAML configuration file and return an empty mapping when blank."""

        config_path = path or self.standards_path
        with config_path.open(encoding="utf-8") as config_file:
            return yaml.safe_load(config_file) or {}

    @property
    def standards(self) -> dict[str, Any]:
        """Load organization standards from the configured YAML file."""

        return self.load_yaml(self.standards_path)

    @property
    def pricing(self) -> dict[str, Any]:
        """Load model pricing from the configured YAML file."""

        return self.load_yaml(self.pricing_path)
