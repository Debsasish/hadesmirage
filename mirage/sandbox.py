from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

import wasmtime

from mirage.common import after, now


@lru_cache(maxsize=1)
def compiled_template() -> tuple[wasmtime.Engine, wasmtime.Module, str]:
    config = wasmtime.Config()
    config.consume_fuel = True
    config.wasm_threads = False
    engine = wasmtime.Engine(config)
    binary = wasmtime.wat2wasm(files("mirage.resources").joinpath("supplier.wat").read_text())
    module = wasmtime.Module(engine, binary)
    if module.imports:
        raise ValueError("Decoy templates may not import any host capability")
    return engine, module, hashlib.sha256(binary).hexdigest()


class Sandbox:
    def __init__(self) -> None:
        self.engine, self.module, self.module_digest = compiled_template()
        self.attestation = self.verify()
        self.ready = self.attestation["verified"]

    def verify(self) -> dict[str, Any]:
        probes: list[dict[str, Any]] = []
        capabilities = {
            "production": ("wasi_snapshot_preview1", "sock_send"),
            "control-plane": ("wasi_snapshot_preview1", "sock_recv"),
            "metadata": ("wasi:sockets/tcp", "connect"),
            "external-network": ("wasi_snapshot_preview1", "sock_accept"),
            "dns": ("wasi:sockets/ip-name-lookup", "resolve-addresses"),
            "filesystem": ("wasi_snapshot_preview1", "path_open"),
            "process-execution": ("wasi_snapshot_preview1", "proc_exit"),
            "environment-credentials": ("wasi_snapshot_preview1", "environ_get"),
        }
        for target, (namespace, name) in capabilities.items():
            probe = wasmtime.Module(
                self.engine,
                f"""
                (module
                  (import "{namespace}" "{name}" (func $attempt))
                  (func (export "probe") (call $attempt)))
            """,
            )
            store = wasmtime.Store(self.engine)
            store.set_fuel(1000)
            linker = wasmtime.Linker(self.engine)
            try:
                instance = linker.instantiate(store, probe)
                instance.exports(store)["probe"](store)
            except wasmtime.WasmtimeError:
                denied = True
            else:
                denied = False
            probes.append(
                {
                    "target": target,
                    "denied": denied,
                    "method": "actual Wasmtime linker capability probe",
                    "evidence": f"{namespace}.{name}: unlinked host capability"
                    if denied
                    else "unexpected capability",
                }
            )
        self.respond("supplier.lookup", {"requests": 0, "changes": 0}, 0)
        return {
            "verified": all(item["denied"] for item in probes) and not self.module.imports,
            "verified_at": now(),
            "expires_at": after(3600),
            "module_sha256": self.module_digest,
            "runtime": "Wasmtime, no imports / no WASI",
            "memory_limit_bytes": 65536,
            "fuel_per_request": 100000,
            "host_imports": 0,
            "probes": probes,
            "scope": "Capability isolation of the Wasm runtime, not a TCP firewall or P3 gateway test",
        }

    def available(self) -> bool:
        return (
            self.ready
            and self.attestation["verified"]
            and self.attestation["expires_at"] > now()
            and self.attestation["module_sha256"] == self.module_digest
        )

    def respond(
        self, tool: str, state: dict[str, int], variant: int
    ) -> tuple[dict[str, Any], dict[str, int]]:
        operation = {
            "supplier.lookup": 1,
            "invoice.compare": 2,
            "customer.export": 3,
            "infrastructure.delete": 3,
        }.get(tool, 0)
        store = wasmtime.Store(self.engine)
        store.set_limits(memory_size=65536, memories=1, tables=0, instances=1)
        store.set_fuel(100000)
        # No WASI context, linker definitions, files, sockets, environment, or host functions.
        instance = wasmtime.Instance(store, self.module, [])
        exports = instance.exports(store)
        exports["restore"](store, state.get("requests", 0), state.get("changes", 0))
        pointer = exports["respond"](store, operation, variant)
        length = exports["length"](store, pointer)
        memory = exports["memory"]
        if not isinstance(memory, wasmtime.Memory) or not 1 <= length <= 2048:
            raise ValueError("Invalid bounded decoy response")
        result = json.loads(bytes(memory.read(store, pointer, pointer + length)))
        restored = {
            "requests": exports["requests"](store),
            "changes": exports["changes"](store),
        }
        return result, restored
