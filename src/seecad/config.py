"""Environment-driven configuration with no secret material in repr output."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_WORKER_BUILD_ID = re.compile(r"sha256-[a-f0-9]{64}\Z")


def derive_worker_build_id(entries: Iterable[tuple[str, bytes]], *, seed: str) -> str:
    """Derive a stable identity from named build inputs without embedding their content."""

    if not seed or len(seed.encode("utf-8")) > 1024 or "\x00" in seed:
        raise ValueError("worker build seed is invalid")
    digest = hashlib.sha256()
    digest.update(b"seecad-worker-build-v1\0")
    digest.update(seed.encode("utf-8"))
    digest.update(b"\0")
    for name, content in sorted(entries, key=lambda item: item[0]):
        if not name or "\x00" in name or "\n" in name:
            raise ValueError("worker build input name is invalid")
        encoded_name = name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256-{digest.hexdigest()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEECAD_",
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    data_dir: Path = Path(".seecad")
    database_path: Path | None = None
    max_artifact_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=1024,
        le=2 * 1024 * 1024 * 1024,
    )

    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(
        default="gpt-5.6",
        validation_alias=AliasChoices("SEECAD_MODEL", "SEECAD_OPENAI_MODEL"),
    )
    openai_reasoning_mode: Literal["pro", "standard"] = Field(
        default="pro",
        validation_alias=AliasChoices("SEECAD_REASONING_MODE", "SEECAD_OPENAI_REASONING_MODE"),
    )
    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = Field(
        default="max",
        validation_alias=AliasChoices("SEECAD_REASONING_EFFORT", "SEECAD_OPENAI_REASONING_EFFORT"),
    )
    openai_timeout_seconds: float = Field(default=480.0, ge=5, le=600)
    openai_max_output_tokens: int = Field(default=16_000, ge=1_000, le=100_000)

    openscad_mode: Literal["auto", "docker", "remote"] = "docker"
    openscad_binary: str = "openscad"
    openscad_docker_binary: str = "docker"
    openscad_docker_image: str = Field(
        default="seecad-openscad:local",
        validation_alias=AliasChoices("SEECAD_OPENSCAD_IMAGE", "SEECAD_OPENSCAD_DOCKER_IMAGE"),
    )
    openscad_timeout_seconds: float = Field(default=120.0, ge=1, le=1800)
    openscad_worker_socket: Path = Path("/run/seecad/worker.sock")
    openscad_worker_build_id: str | None = Field(
        default=None,
        pattern=r"^sha256-[a-f0-9]{64}$",
    )
    openscad_worker_build_id_file: Path = Path("/opt/seecad/worker-build-id")
    openscad_health_timeout_seconds: float = Field(default=2.0, ge=0.1, le=10.0)
    openscad_memory: str = Field(default="1g", pattern=r"^[1-9][0-9]*[bkmg]$")
    openscad_cpus: float = Field(default=2.0, gt=0, le=32)
    openscad_include_paths: list[Path] = Field(default_factory=lambda: [Path("vendor")])
    nopscad_root: Path = Path("vendor/NopSCADlib")

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        validation_alias=AliasChoices("SEECAD_ALLOWED_ORIGINS", "SEECAD_CORS_ORIGINS"),
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            return json.loads(stripped)
        return [item.strip() for item in stripped.split(",") if item.strip()]

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_empty_api_key(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("openscad_binary", "openscad_docker_binary")
    @classmethod
    def validate_binary_name(cls, value: str) -> str:
        if not value or "\x00" in value or "\n" in value:
            raise ValueError("binary name is invalid")
        return value

    @field_validator("openscad_worker_socket", "openscad_worker_build_id_file")
    @classmethod
    def validate_worker_socket(cls, value: Path) -> Path:
        if not value.is_absolute() or "\x00" in str(value) or "\n" in str(value):
            raise ValueError("OpenSCAD worker paths must be absolute")
        return value

    @property
    def resolved_worker_build_id(self) -> str:
        if self.openscad_worker_build_id is not None:
            return self.openscad_worker_build_id
        try:
            from_file = self.openscad_worker_build_id_file.read_text(encoding="ascii").strip()
        except OSError:
            package_root = Path(__file__).resolve().parent
            entries = (
                (path.name, path.read_bytes())
                for path in package_root.glob("*.py")
                if path.is_file() and not path.is_symlink()
            )
            return derive_worker_build_id(entries, seed="editable-source-tree")
        if _WORKER_BUILD_ID.fullmatch(from_file) is None:
            raise ValueError("worker build identity file is invalid")
        return from_file

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser().resolve()

    @property
    def resolved_database_path(self) -> Path:
        configured = self.database_path or (self.data_dir / "index.sqlite3")
        return configured.expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
