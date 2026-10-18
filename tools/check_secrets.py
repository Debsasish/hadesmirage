"""Known-secret-format smoke check of source only; not a full secrets or security scanner."""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".venv",
    ".local",
    ".git",
    "node_modules",
    "dist",
    "playwright-report",
    "test-results",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".md",
    ".txt",
    ".cmd",
    ".ps1",
    ".lock",
    ".sql",
}
PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"sk-(?:proj-|ant-api)[A-Za-z0-9_-]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def main() -> None:
    failures = []
    checked = 0
    for directory, subdirectories, names in os.walk(ROOT):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in EXCLUDED and not name.endswith(".egg-info")
        ]
        for name in names:
            path = Path(directory) / name
            if path.suffix not in SUFFIXES:
                continue
            checked += 1
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if any(pattern.search(line) for pattern in PATTERNS):
                    failures.append(f"{path.relative_to(ROOT)}:{number}")
    if failures:
        raise SystemExit(
            "Potential secret format detected (values not printed):\n" + "\n".join(failures)
        )
    print(f"PASS: {checked} source files checked for selected key/private-key formats.")
    print(
        "This is a bounded smoke check, not a guarantee that all secrets or vulnerabilities are absent."
    )


if __name__ == "__main__":
    main()
