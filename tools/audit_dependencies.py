"""Query OSV using public locked PyPI names/versions only, with verified TLS."""

from __future__ import annotations

import json
import re
import ssl
from pathlib import Path

import httpx

from mirage.common import now

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    packages = []
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if match:
            packages.append((match[1], match[2]))
    if not packages:
        raise SystemExit("No exact locked packages found; audit was not performed")
    request = {
        "queries": [
            {
                "package": {"name": re.sub(r"[-_.]+", "-", name).lower(), "ecosystem": "PyPI"},
                "version": version,
            }
            for name, version in packages
        ]
    }
    # Python's default SSL context loads the Windows system trust store; verification stays on.
    with httpx.Client(verify=ssl.create_default_context(), timeout=40) as client:
        response = client.post("https://api.osv.dev/v1/querybatch", json=request)
        response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or len(body.get("results", [])) != len(packages):
        raise SystemExit("Unexpected OSV response; no clean-audit claim can be made")
    findings = [
        {"package": name, "version": version, "advisories": result["vulns"]}
        for (name, version), result in zip(packages, body["results"], strict=True)
        if result.get("vulns")
    ]
    report = {
        "checked_at": now(),
        "source": "https://api.osv.dev/v1/querybatch",
        "package_count": len(packages),
        "findings": findings,
        "scope": "Known public advisory matches for exact third-party PyPI lock versions; no private project source or credentials sent",
        "limitations": "Not a source-code audit, exploit verification, or guarantee that all vulnerabilities are known",
    }
    directory = ROOT / ".local"
    directory.mkdir(exist_ok=True)
    (directory / "python-dependency-audit.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    if findings:
        raise SystemExit("Dependency advisory matches require review")


if __name__ == "__main__":
    main()
