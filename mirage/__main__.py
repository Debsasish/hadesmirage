from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path

import httpx

from mirage import db
from mirage.backend import HttpBackend
from mirage.common import now, uid
from mirage.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def wait_for_api(settings: Settings, process: subprocess.Popen[bytes]) -> None:
    with httpx.Client(timeout=1, trust_env=False) as client:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("API exited during startup; inspect .local/api.log")
            try:
                result = client.get(f"http://127.0.0.1:{settings.api_port}/health")
                if result.status_code == 200 and result.json().get("ready"):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    raise RuntimeError("API readiness timed out; inspect .local/api.log")


def demo(settings: Settings) -> None:
    credentials = json.loads((settings.data_dir / "fixture-credentials.json").read_text())
    token = credentials["tenant-demo/admin"]
    with httpx.Client(
        base_url=f"http://127.0.0.1:{settings.api_port}",
        timeout=30,
        trust_env=False,
        headers={"Authorization": "Bearer " + token},
    ) as client:
        approvals: list[str] = []
        scenarios = (
            ["legitimate-lookup"] * 6
            + ["benign-quotation"] * 2
            + [
                "blocked-payment",
                "blocked-payment",
                "external-probing",
                "external-probing",
                "delegation-escalation",
            ]
        )
        for scenario in scenarios:
            response = client.post(
                "/v1/laboratory/run",
                json={"scenario": scenario},
                headers={"Idempotency-Key": uid()},
            )
            response.raise_for_status()
            body = response.json()
            if body.get("approval"):
                approvals.append(body["approval"]["id"])
        if approvals:
            response = client.post(
                "/v1/laboratory/run",
                json={
                    "scenario": "approval-substitution",
                    "approval_id": approvals[0],
                },
                headers={"Idempotency-Key": uid()},
            )
            response.raise_for_status()
        cases = client.get("/v1/incidents").json()["items"]
        if settings.model_provider == "fixture":
            for case in cases[:4]:
                response = client.post(
                    f"/v1/incidents/{case['id']}/investigate",
                    json={},
                    headers={"Idempotency-Key": uid()},
                )
                response.raise_for_status()
    (settings.data_dir / "demo-seed.json").write_text(
        json.dumps(
            {
                "created_at": now(),
                "origin": "actual local HTTP requests over synthetic data",
                "model": settings.model_provider,
                "scenario_count": len(scenarios) + 1,
            },
            indent=2,
        )
    )
    print("Recorded synthetic scenarios seeded through the actual HTTP API.", flush=True)


def run(settings: Settings, empty: bool = False) -> None:
    build = ROOT / "apps" / "dashboard" / "dist" / "index.html"
    if not build.is_file():
        raise RuntimeError(
            "Console is not built. Run setup.cmd first, or npm.cmd run build in apps\\dashboard."
        )
    for port in (settings.api_port, settings.backend_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise RuntimeError(
                    f"Port {port} is already in use. No existing process was stopped."
                ) from error
    env = {**os.environ, "MIRAGE_DATA_DIR": str(settings.data_dir.resolve())}
    processes: list[subprocess.Popen[bytes]] = []
    logs = []
    try:
        for module, port, name in (
            ("mirage.backend:create_backend_app", settings.backend_port, "backend"),
            ("mirage.api:create_app", settings.api_port, "api"),
        ):
            log = (settings.data_dir / f"{name}.log").open("ab")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        module,
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
        wait_for_api(settings, processes[1])
        if not HttpBackend(settings).healthy():
            raise RuntimeError("Signed backend readiness failed; inspect .local/backend.log")
        if not empty and not (settings.data_dir / "demo-seed.json").exists():
            demo(settings)
        (settings.data_dir / "run.json").write_text(
            json.dumps(
                {
                    "api_pid": processes[1].pid,
                    "backend_pid": processes[0].pid,
                    "api_port": settings.api_port,
                    "backend_port": settings.backend_port,
                    "started_at": now(),
                    "profile": settings.profile,
                },
                indent=2,
            )
        )
        print(f"\nHades Mirage: http://127.0.0.1:{settings.api_port}", flush=True)
        print(f"Local access code: {settings.access_code}", flush=True)
        print("Identities: admin / analyst / approver (same local launch code).", flush=True)
        print(
            f"{settings.profile} | synthetic data | no Docker | provider: {settings.model_provider} | advisory only.",
            flush=True,
        )
        print(
            "Press Ctrl+C to stop only the two child processes started by this launcher.\n",
            flush=True,
        )
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("A child service exited; inspect the project-local logs")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()


def reset(settings: Settings, confirmation: str) -> None:
    if confirmation != "SYNTHETIC-LOCAL-DATA":
        raise RuntimeError(
            "Reset requires --confirm SYNTHETIC-LOCAL-DATA; stop the launcher first."
        )
    if settings.database_url and not settings.database_url.startswith("sqlite:"):
        raise RuntimeError(
            "Reset does not modify PostgreSQL. Use an approved database retention procedure."
        )
    # Only individually named files created by this package may be removed.
    for name in (
        "mirage.sqlite3",
        "mirage.sqlite3-wal",
        "mirage.sqlite3-shm",
        "backend.sqlite3",
        "backend.sqlite3-wal",
        "backend.sqlite3-shm",
        "fixture-credentials.json",
        "demo-seed.json",
        "run.json",
    ):
        target = (settings.data_dir / name).resolve()
        if target.parent != settings.data_dir.resolve():
            raise RuntimeError("Unexpected reset path")
        target.unlink(missing_ok=True)
    print(
        "Named synthetic database and fixture files removed. Launch code and unrelated files preserved."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Hades Mirage native local laboratory. No Docker.")
    sub = parser.add_subparsers(dest="command", required=True)
    launch = sub.add_parser("run", help="Start signed backend and API/console on loopback")
    launch.add_argument(
        "--empty", action="store_true", help="Do not seed recorded laboratory scenarios"
    )
    sub.add_parser("demo", help="Replay bounded synthetic scenarios through the running HTTP API")
    sub.add_parser("migrate", help="Apply versioned authoritative-store schema")
    sub.add_parser(
        "verify-isolation", help="Run actual Wasmtime capability probes, not TCP firewall tests"
    )
    sub.add_parser("provenance", help="Print reviewed source pins and profile boundaries")
    export = sub.add_parser("export-openapi", help="Export the implemented OpenAPI contract")
    export.add_argument("--output", type=Path, default=ROOT / "contracts" / "runtime-openapi.json")
    reset_parser = sub.add_parser(
        "reset", help="Remove only named synthetic files while services are stopped"
    )
    reset_parser.add_argument("--confirm", default="")
    sub.add_parser(
        "cloud",
        help="Cloud Run entrypoint (P2-cloud, IAP sign-in, synthetic data, buildpacks; no Docker)",
    )
    args = parser.parse_args()
    if args.command == "cloud":
        from mirage.cloud import apply_cloud_defaults

        apply_cloud_defaults()
    settings = Settings()
    settings.prepare()
    try:
        if args.command == "run":
            run(settings, args.empty)
        elif args.command == "cloud":
            from mirage.cloud import run_cloud

            run_cloud(settings)
        elif args.command == "demo":
            demo(settings)
        elif args.command == "provenance":
            print(files("mirage.resources").joinpath("provenance.json").read_text())
        elif args.command == "verify-isolation":
            from mirage.sandbox import Sandbox

            proof = Sandbox().attestation
            (settings.data_dir / "isolation-evidence.json").write_text(json.dumps(proof, indent=2))
            print(json.dumps(proof, indent=2))
            if not proof["verified"]:
                raise RuntimeError("Capability isolation verification failed")
        elif args.command == "reset":
            reset(settings, args.confirm)
        else:
            from mirage.api import create_app

            app = create_app(settings)
            try:
                if args.command == "export-openapi":
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
                    print(f"Runtime contract written to {args.output}")
                else:
                    print(
                        f"Schema version {db.SCHEMA_VERSION} applied. No production data imported."
                    )
            finally:
                app.state.service.db.close()
    except KeyboardInterrupt:
        print("\nNative services stopped.")
    except (RuntimeError, OSError, httpx.HTTPError) as error:
        print(f"Mirage: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
