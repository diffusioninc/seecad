"""Bounded OpenSCAD execution using local, Docker, or UDS worker engines."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn

import httpx

from seecad.config import Settings
from seecad.errors import CompilationError, EngineUnavailableError
from seecad.scad import _library_provenance

WORKER_PROTOCOL = "1"
WORKER_SOURCE_LIMIT = 8 * 1024 * 1024
WORKER_DIAGNOSTICS_LIMIT = 3 * 1024
WORKER_HEALTH_BODY_LIMIT = 1024

HEADER_PROTOCOL = "X-SeeCAD-Protocol"
HEADER_FORMAT = "X-SeeCAD-Format"
HEADER_SHA256 = "X-SeeCAD-Artifact-SHA256"
HEADER_SIZE = "X-SeeCAD-Artifact-Size"
HEADER_DURATION_MS = "X-SeeCAD-Duration-Ms"
HEADER_OPENSCAD_VERSION = "X-SeeCAD-OpenSCAD-Version"
HEADER_NOP_REVISION = "X-SeeCAD-NopSCAD-Revision"
HEADER_NOP_TREE_SHA256 = "X-SeeCAD-NopSCAD-Tree-SHA256"
HEADER_DIAGNOSTICS = "X-SeeCAD-Diagnostics-Base64"
HEADER_WORKER_STATE = "X-SeeCAD-Worker-State"
HEADER_WORKER_BUILD_ID = "X-SeeCAD-Worker-Build-Id"
HEADER_SOURCE_SHA256 = "X-SeeCAD-Source-SHA256"

_HEX_40 = re.compile(r"[a-f0-9]{40}\Z")
_HEX_64 = re.compile(r"[a-f0-9]{64}\Z")
_SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,127}\Z")
_UINT = re.compile(r"(?:0|[1-9][0-9]{0,19})\Z")


@dataclass(frozen=True, slots=True)
class NopSCADProvenance:
    revision: str
    tree_sha256: str


@dataclass(frozen=True, slots=True)
class CompilationProvenance:
    protocol: str
    worker_build_id: str
    openscad_version: str
    nopscad_revision: str
    nopscad_tree_sha256: str
    source_sha256: str


def verified_nopscad_provenance(root: Path) -> NopSCADProvenance:
    """Recompute the vendored tree digest and return its pinned identity."""

    payload = _library_provenance(root.expanduser().resolve())
    revision = payload.get("revision")
    tree_sha256 = payload.get("tree_sha256")
    if (
        not isinstance(revision, str)
        or _HEX_40.fullmatch(revision) is None
        or not isinstance(tree_sha256, str)
        or _HEX_64.fullmatch(tree_sha256) is None
    ):
        raise EngineUnavailableError("Pinned NopSCADlib provenance verification failed")
    return NopSCADProvenance(revision=revision, tree_sha256=tree_sha256)


class _WorkerProtocolError(Exception):
    """An intentionally message-free worker trust-boundary failure."""


@dataclass(frozen=True, slots=True)
class CompilationResult:
    content: bytes
    format: Literal["stl", "3mf"]
    engine: Literal["local", "docker", "remote"]
    duration_seconds: float
    diagnostics: str
    provenance: CompilationProvenance | None = None


class OpenSCADEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def available_mode(self) -> Literal["local", "docker", "remote"] | None:
        mode = self.settings.openscad_mode
        if mode == "remote":
            return "remote" if self._remote_health() else None
        docker = (
            shutil.which(self.settings.openscad_docker_binary) is not None
            and self._docker_image_available()
        )
        if mode in {"auto", "docker"}:
            return "docker" if docker else None
        return None

    def is_available(self) -> bool:
        return self.available_mode() is not None

    def compile(
        self, source: str, *, output_format: Literal["stl", "3mf"] = "stl"
    ) -> CompilationResult:
        if output_format not in {"stl", "3mf"}:
            raise CompilationError("Unsupported OpenSCAD output format")
        encoded = source.encode("utf-8")
        if len(encoded) > WORKER_SOURCE_LIMIT:
            raise CompilationError("SCAD source exceeds the 8 MiB execution limit")
        mode = self.available_mode()
        if mode is None:
            raise EngineUnavailableError(
                "OpenSCAD is unavailable; configure the Docker or remote worker engine"
            )
        provenance = verified_nopscad_provenance(self.settings.nopscad_root)
        if mode == "remote":
            return self._compile_remote(
                encoded,
                output_format=output_format,
                provenance=provenance,
            )
        with tempfile.TemporaryDirectory(prefix="seecad-compile-") as temp:
            root = Path(temp)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir(mode=0o755)
            output_dir.mkdir(mode=0o777)
            source_path = input_dir / "model.scad"
            output_path = output_dir / f"model.{output_format}"
            source_path.write_bytes(encoded)
            source_path.chmod(0o444)
            if mode == "local":
                argv, env = self._local_argv(source_path, output_path), self._local_env()
                cidfile = None
            else:
                cidfile = root / "container.cid"
                argv, env = (
                    self._docker_argv(input_dir, output_dir, output_format, cidfile),
                    self._docker_env(),
                )
            started = time.monotonic()
            completed = self._execute(argv, env=env, cidfile=cidfile)
            duration = time.monotonic() - started
            diagnostics = self._diagnostics(completed.stdout, completed.stderr)
            if completed.returncode != 0:
                raise CompilationError(
                    "OpenSCAD rejected the generated model",
                    details={
                        "engine": mode,
                        "returncode": completed.returncode,
                        "diagnostics": diagnostics,
                    },
                )
            try:
                content = output_path.read_bytes()
            except FileNotFoundError as exc:
                raise CompilationError(
                    "OpenSCAD exited without producing an output artifact",
                    details={"engine": mode, "diagnostics": diagnostics},
                ) from exc
            if not content:
                raise CompilationError("OpenSCAD produced an empty output artifact")
            if len(content) > self.settings.max_artifact_bytes:
                raise CompilationError(
                    "OpenSCAD output exceeds the artifact limit",
                    details={
                        "size_bytes": len(content),
                        "max_bytes": self.settings.max_artifact_bytes,
                    },
                )
            return CompilationResult(
                content=content,
                format=output_format,
                engine=mode,
                duration_seconds=duration,
                diagnostics=diagnostics,
            )

    def _remote_client(self, *, health: bool) -> httpx.Client:
        timeout_seconds = (
            self.settings.openscad_health_timeout_seconds
            if health
            else self.settings.openscad_timeout_seconds + 5.0
        )
        transport = httpx.HTTPTransport(
            uds=os.fspath(self.settings.openscad_worker_socket),
            retries=0,
        )
        return httpx.Client(
            base_url="http://seecad-worker",
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": f"seecad-worker-protocol/{WORKER_PROTOCOL}"},
        )

    def _remote_health(self) -> bool:
        try:
            provenance = verified_nopscad_provenance(self.settings.nopscad_root)
            build_id = self.settings.resolved_worker_build_id
            with (
                self._remote_client(health=True) as client,
                client.stream("GET", "/v1/health") as response,
            ):
                if response.status_code != 204:
                    return False
                self._validate_common_worker_headers(
                    response,
                    provenance,
                    build_id,
                )
                size = 0
                for chunk in response.iter_raw():
                    size += len(chunk)
                    if size > WORKER_HEALTH_BODY_LIMIT:
                        return False
                return size == 0
        except (
            EngineUnavailableError,
            _WorkerProtocolError,
            httpx.HTTPError,
            OSError,
            ValueError,
        ):
            return False

    def _compile_remote(
        self,
        source: bytes,
        *,
        output_format: Literal["stl", "3mf"],
        provenance: NopSCADProvenance,
    ) -> CompilationResult:
        try:
            build_id = self.settings.resolved_worker_build_id
            with (
                self._remote_client(health=False) as client,
                client.stream(
                    "POST",
                    "/v1/compile",
                    params={"format": output_format},
                    content=source,
                    headers={
                        "Content-Type": "text/plain; charset=utf-8",
                        "Accept": "model/stl" if output_format == "stl" else "model/3mf",
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    self._raise_remote_status(response)
                version = self._validate_common_worker_headers(
                    response,
                    provenance,
                    build_id,
                )
                source_sha256 = hashlib.sha256(source).hexdigest()
                if self._required_header(response, HEADER_SOURCE_SHA256, 64) != source_sha256:
                    raise _WorkerProtocolError
                if self._required_header(response, HEADER_FORMAT, 8) != output_format:
                    raise _WorkerProtocolError
                expected_sha = self._required_header(response, HEADER_SHA256, 64)
                if _HEX_64.fullmatch(expected_sha) is None:
                    raise _WorkerProtocolError
                expected_size = self._unsigned_header(response, HEADER_SIZE)
                if expected_size == 0 or expected_size > self.settings.max_artifact_bytes:
                    raise _WorkerProtocolError
                duration_ms = self._unsigned_header(response, HEADER_DURATION_MS)
                max_duration_ms = int((self.settings.openscad_timeout_seconds + 5.0) * 1000)
                if duration_ms > max_duration_ms:
                    raise _WorkerProtocolError
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    if _UINT.fullmatch(content_length) is None:
                        raise _WorkerProtocolError
                    if int(content_length) != expected_size:
                        raise _WorkerProtocolError
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise _WorkerProtocolError
                diagnostics = self._decode_diagnostics(response)
                body = bytearray()
                digest = hashlib.sha256()
                for chunk in response.iter_raw(chunk_size=64 * 1024):
                    if len(body) + len(chunk) > self.settings.max_artifact_bytes:
                        raise CompilationError("OpenSCAD output exceeds the artifact limit")
                    body.extend(chunk)
                    digest.update(chunk)
                if len(body) != expected_size or digest.hexdigest() != expected_sha:
                    raise _WorkerProtocolError
                return CompilationResult(
                    content=bytes(body),
                    format=output_format,
                    engine="remote",
                    duration_seconds=duration_ms / 1000.0,
                    diagnostics=diagnostics,
                    provenance=CompilationProvenance(
                        protocol=WORKER_PROTOCOL,
                        worker_build_id=build_id,
                        openscad_version=version,
                        nopscad_revision=provenance.revision,
                        nopscad_tree_sha256=provenance.tree_sha256,
                        source_sha256=source_sha256,
                    ),
                )
        except _WorkerProtocolError as exc:
            raise EngineUnavailableError(
                "OpenSCAD worker protocol validation failed",
                details={"reason": "invalid_worker_response"},
            ) from exc
        except httpx.TimeoutException as exc:
            raise CompilationError(
                "OpenSCAD compilation timed out",
                details={"timeout_seconds": self.settings.openscad_timeout_seconds},
            ) from exc
        except (httpx.TransportError, OSError) as exc:
            raise EngineUnavailableError("OpenSCAD worker is unavailable") from exc
        except ValueError as exc:
            raise EngineUnavailableError("OpenSCAD worker build identity is unavailable") from exc

    @staticmethod
    def _required_header(response: httpx.Response, name: str, max_length: int) -> str:
        value = response.headers.get(name)
        if value is None or not value or len(value) > max_length:
            raise _WorkerProtocolError
        return str(value)

    @classmethod
    def _unsigned_header(cls, response: httpx.Response, name: str) -> int:
        value = cls._required_header(response, name, 20)
        if _UINT.fullmatch(value) is None:
            raise _WorkerProtocolError
        return int(value)

    @classmethod
    def _validate_common_worker_headers(
        cls,
        response: httpx.Response,
        provenance: NopSCADProvenance,
        expected_build_id: str,
    ) -> str:
        if cls._required_header(response, HEADER_PROTOCOL, 8) != WORKER_PROTOCOL:
            raise _WorkerProtocolError
        build_id = cls._required_header(response, HEADER_WORKER_BUILD_ID, 80)
        if build_id != expected_build_id:
            raise _WorkerProtocolError
        if cls._required_header(response, HEADER_NOP_REVISION, 40) != provenance.revision:
            raise _WorkerProtocolError
        if cls._required_header(response, HEADER_NOP_TREE_SHA256, 64) != provenance.tree_sha256:
            raise _WorkerProtocolError
        version = cls._required_header(response, HEADER_OPENSCAD_VERSION, 128)
        if _SAFE_VERSION.fullmatch(version) is None:
            raise _WorkerProtocolError
        return version

    @classmethod
    def _decode_diagnostics(cls, response: httpx.Response) -> str:
        encoded = response.headers.get(HEADER_DIAGNOSTICS)
        if encoded is None or len(encoded) > 4 * 1024:
            raise _WorkerProtocolError
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise _WorkerProtocolError from exc
        if len(decoded) > WORKER_DIAGNOSTICS_LIMIT:
            raise _WorkerProtocolError
        return decoded.decode("utf-8", errors="replace")

    @staticmethod
    def _raise_remote_status(response: httpx.Response) -> NoReturn:
        status = response.status_code
        if status == 503:
            busy = response.headers.get(HEADER_WORKER_STATE) == "busy"
            raise EngineUnavailableError(
                "OpenSCAD worker is busy" if busy else "OpenSCAD worker is unavailable",
                details={"reason": "busy" if busy else "worker_unavailable"},
            )
        if status in {400, 413, 415, 422}:
            raise CompilationError(
                "OpenSCAD worker rejected the model",
                details={"worker_status": status},
            )
        raise EngineUnavailableError(
            "OpenSCAD worker returned an unexpected status",
            details={"worker_status": status},
        )

    def _local_argv(self, source: Path, output: Path) -> list[str]:
        return [self.settings.openscad_binary, "-o", os.fspath(output), os.fspath(source)]

    def _local_env(self) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
        }
        include_paths = [
            os.fspath(path.expanduser().resolve())
            for path in self.settings.openscad_include_paths
            if path.expanduser().resolve().is_dir()
        ]
        inherited = os.environ.get("OPENSCADPATH")
        if inherited:
            include_paths.append(inherited)
        if include_paths:
            env["OPENSCADPATH"] = os.pathsep.join(include_paths)
        return env

    def _docker_argv(
        self,
        input_dir: Path,
        output_dir: Path,
        output_format: str,
        cidfile: Path,
    ) -> list[str]:
        size = self.settings.max_artifact_bytes
        argv = [
            self.settings.openscad_docker_binary,
            "run",
            "--rm",
            "--pull",
            "never",
            "--cidfile",
            os.fspath(cidfile),
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            self.settings.openscad_memory,
            "--cpus",
            str(self.settings.openscad_cpus),
            "--ulimit",
            f"fsize={size}:{size}",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--tmpfs",
            "/home/seecad:rw,noexec,nosuid,size=16m,uid=10001,gid=10001",
            "--mount",
            f"type=bind,src={input_dir},dst=/input,readonly",
            "--mount",
            f"type=bind,src={output_dir},dst=/output",
        ]
        for index, configured in enumerate(self.settings.openscad_include_paths):
            include_path = configured.expanduser().resolve()
            if include_path.is_dir():
                argv.extend(
                    [
                        "--mount",
                        f"type=bind,src={include_path},dst=/libraries/{index},readonly",
                    ]
                )
        mounted_include_paths = [
            f"/libraries/{index}"
            for index, configured in enumerate(self.settings.openscad_include_paths)
            if configured.expanduser().resolve().is_dir()
        ]
        if mounted_include_paths:
            argv.extend(["--env", f"OPENSCADPATH={':'.join(mounted_include_paths)}:/opt/libraries"])
        argv.extend(
            [
                self.settings.openscad_docker_image,
                "-o",
                f"/output/model.{output_format}",
                "/input/model.scad",
            ]
        )
        return argv

    @staticmethod
    def _docker_env() -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "DOCKER_HOST": os.environ.get("DOCKER_HOST", ""),
        }

    def _docker_image_available(self) -> bool:
        try:
            completed = subprocess.run(
                [
                    self.settings.openscad_docker_binary,
                    "image",
                    "inspect",
                    self.settings.openscad_docker_image,
                ],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                env=self._docker_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    def _execute(
        self, argv: list[str], *, env: dict[str, str], cidfile: Path | None
    ) -> subprocess.CompletedProcess[str]:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=self.settings.openscad_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            if cidfile is not None:
                self._remove_timed_out_container(cidfile)
            raise CompilationError(
                "OpenSCAD compilation timed out",
                details={"timeout_seconds": self.settings.openscad_timeout_seconds},
            ) from exc
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)

    def _remove_timed_out_container(self, cidfile: Path) -> None:
        try:
            container_id = cidfile.read_text(encoding="ascii").strip()
        except OSError:
            return
        if not container_id or any(char not in "0123456789abcdef" for char in container_id):
            return
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                [self.settings.openscad_docker_binary, "rm", "-f", container_id],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                env=self._docker_env(),
            )

    @staticmethod
    def _diagnostics(stdout: str, stderr: str) -> str:
        combined = "\n".join(part.strip() for part in (stdout, stderr) if part.strip())
        return combined[-16_000:]
