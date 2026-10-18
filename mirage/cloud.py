"""Cloud Run launcher for the P2-cloud demonstration profile (synthetic data only).

Cloud Run builds this source with Google Cloud buildpacks (``gcloud run deploy --source .``).
No Dockerfile and no local Docker are involved. One container runs two child processes:
the signed synthetic backend on container loopback and the API/console on ``0.0.0.0:$PORT``.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import MutableMapping
from pathlib import Path
from types import FrameType

import httpx

from mirage.backend import HttpBackend
from mirage.config import Settings

ROOT = Path(__file__).resolve().parents[1]
CLOUD_DEFAULTS = {
    "MIRAGE_PROFILE": "P2-cloud",
    "MIRAGE_AUTH_MODE": "iap",
    "MIRAGE_LOCAL_LOGIN": "false",
    # Cloud Run's writable filesystem is in memory: state here is per instance and ephemeral.
    "MIRAGE_DATA_DIR": "/tmp/mirage",
}
SHUTDOWN_SECONDS = 8


class StopRequested(Exception):
    """Raised by the SIGTERM handler so child services are stopped in order."""


def apply_cloud_defaults(environ: MutableMapping[str, str] | None = None) -> None:
    environ = os.environ if environ is None else environ
    for key, value in CLOUD_DEFAULTS.items():
        environ.setdefault(key, value)


def cloud_port(environ: MutableMapping[str, str] | None = None) -> int:
    raw = (os.environ if environ is None else environ).get("PORT", "8080")
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise RuntimeError("PORT must be a TCP port number")
    return int(raw)


def check_cloud_settings(
    settings: Settings, port: int, environ: MutableMapping[str, str] | None = None
) -> None:
    environ = os.environ if environ is None else environ
    if settings.profile != "P2-cloud" or settings.auth_mode != "iap" or settings.local_login:
        raise RuntimeError(
            "The cloud launcher requires MIRAGE_PROFILE=P2-cloud, MIRAGE_AUTH_MODE=iap "
            "and MIRAGE_LOCAL_LOGIN=false"
        )
    if port == settings.backend_port:
        raise RuntimeError("PORT and MIRAGE_BACKEND_PORT must differ")
    supplied = environ.get("MIRAGE_BACKEND_SECRET", "")
    if supplied and len(supplied) < 32:
        raise RuntimeError("MIRAGE_BACKEND_SECRET must contain at least 32 characters")
    if not (ROOT / "apps" / "dashboard" / "dist" / "index.html").is_file():
        raise RuntimeError(
            "Console build missing: run npm.cmd run build in apps\\dashboard before deploying"
        )


def _free(host: str, port: int) -> None:
    with socket.socket() as probe:
        try:
            probe.bind((host, port))
        except OSError as error:
            raise RuntimeError(f"Port {port} is already in use. Nothing was stopped.") from error


def _uvicorn(module: str, host: str, port: int, env: dict[str, str]) -> subprocess.Popen[bytes]:
    # Logs go to stdout/stderr so Cloud Logging captures them; access logs stay off.
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            module,
            "--factory",
            "--host",
            host,
            "--port",
            str(port),
            "--no-access-log",
            "--timeout-graceful-shutdown",
            str(SHUTDOWN_SECONDS - 2),
        ],
        cwd=ROOT,
        env=env,
    )


def _wait_backend(settings: Settings, process: subprocess.Popen[bytes]) -> None:
    backend = HttpBackend(settings)
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError("Synthetic backend exited during startup")
        if backend.healthy():
            return
        time.sleep(0.2)
    raise RuntimeError("Signed synthetic backend readiness timed out")


def _wait_api(port: int, process: subprocess.Popen[bytes]) -> None:
    with httpx.Client(timeout=2, trust_env=False) as client:
        for _ in range(150):
            if process.poll() is not None:
                raise RuntimeError("API exited during startup")
            try:
                result = client.get(f"http://127.0.0.1:{port}/health")
                if result.status_code == 200 and result.json().get("ready"):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.2)
    raise RuntimeError("API readiness timed out")


def _stop(signum: int, _frame: FrameType | None) -> None:
    raise StopRequested(signum)


def run_cloud(settings: Settings) -> None:
    port = cloud_port()
    check_cloud_settings(settings, port)
    _free("127.0.0.1", settings.backend_port)
    _free("0.0.0.0", port)
    env = {**os.environ, "MIRAGE_DATA_DIR": str(settings.data_dir.resolve())}
    processes: list[subprocess.Popen[bytes]] = []
    previous = signal.signal(signal.SIGTERM, _stop)
    try:
        processes.append(
            _uvicorn("mirage.backend:create_backend_app", "127.0.0.1", settings.backend_port, env)
        )
        _wait_backend(settings, processes[0])
        processes.append(_uvicorn("mirage.api:create_app", "0.0.0.0", port, env))
        _wait_api(port, processes[1])
        print(
            f"Hades Mirage cloud demo | {settings.profile} | synthetic data only | sign-in: "
            f"Google IAP | provider: {settings.model_provider} | AI advisory only",
            flush=True,
        )
        print(
            f"API/console on 0.0.0.0:{port}; signed synthetic backend on container loopback "
            f"127.0.0.1:{settings.backend_port}",
            flush=True,
        )
        if not os.environ.get("MIRAGE_BACKEND_SECRET"):
            print(
                "MIRAGE_BACKEND_SECRET not supplied: using a per-instance generated secret. "
                "Run a single instance (--max-instances 1).",
                flush=True,
            )
        if settings.database_url.startswith("sqlite:"):
            print(
                "State is SQLite inside this instance: it is lost on restart or scale-in.",
                flush=True,
            )
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("A child service exited; see the service logs")
    except StopRequested:
        print("SIGTERM received; stopping the child services.", flush=True)
    finally:
        signal.signal(signal.SIGTERM, previous)
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=SHUTDOWN_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
