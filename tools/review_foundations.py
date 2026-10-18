"""Review only pinned, allowlisted foundation artifacts; never extract uploaded Git history."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from mirage.common import now
from mirage.control import provenance
from mirage.models import HadesReport

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hades-auditor", type=Path, required=True)
    parser.add_argument("--gateway-archive", type=Path, required=True)
    args = parser.parse_args()
    source = provenance()
    code = args.hades_auditor.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(code)).encode() + b"\0" + code).hexdigest()
    if blob != source["hades"]["reviewed_blobs"]["scripts/mcp_manifest_audit.py"]:
        raise SystemExit("Auditor differs from the reviewed pin. No upstream script was executed.")
    result = subprocess.run(
        [
            sys.executable,
            str(args.hades_auditor.resolve()),
            str(ROOT / "tests" / "fixtures" / "procurement-manifest.json"),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    output = json.loads(result.stdout)
    report = HadesReport.model_validate(
        {
            "source_version": source["hades"]["commit"],
            "tool_count": output["tool_count"],
            "tools": output["tools"],
        }
    )
    with args.gateway_archive.open("rb") as archive_file:
        archive_digest = hashlib.file_digest(archive_file, "sha256").hexdigest()
    if archive_digest != source["gateway"]["archive_sha256"]:
        raise SystemExit(
            "Gateway archive differs from the reviewed pin. No archive source was extracted."
        )
    selected = {}
    with zipfile.ZipFile(args.gateway_archive) as archive:
        for name in ("README.md", "LICENSE", "Cargo.toml", "src/proxy.rs"):
            entry = archive.getinfo("agent-gateway/" + name)
            if entry.file_size > 50000:
                raise SystemExit("Unexpected selected-file size")
            content = archive.read(entry)
            selected[name] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    (local / "hades-report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    evidence = {
        "reviewed_at": now(),
        "hades": {
            "commit": source["hades"]["commit"],
            "auditor_blob": blob,
            "execution": "Actual pinned script against only the synthetic procurement manifest fixture",
            "tool_count": report.tool_count,
            "classification": "Heuristic observations; not exploit verification",
        },
        "gateway": {
            "archive_sha256": archive_digest,
            "selected_files": selected,
            "execution": "None. Rust gateway, test PKI and registry were not provisioned.",
            "git_history_copied": False,
            "source_extracted": False,
        },
    }
    (local / "foundation-evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, indent=2))
    print("Typed importable report: .local\\hades-report.json")


if __name__ == "__main__":
    main()
