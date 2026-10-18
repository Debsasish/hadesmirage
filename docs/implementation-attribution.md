# Implementation provenance and attribution

The original project blueprint, its contracts and examples were supplied by the project owner. They remain visible as a historical specification. New runtime code is authored in this workspace; no uploaded Git history, private settings or upstream repository changes were copied.

## Reviewed foundations

| Foundation | Pin / license | Reviewed and exercised scope |
| --- | --- | --- |
| Hades-Blackwatch | `bdeb181d7a998f88d2c9ccced9d35d4e76998072`; Apache-2.0 | README, actual LICENSE and manifest-auditor source reviewed. Exact pinned auditor executed locally against the synthetic procurement manifest only |
| Agent gateway | Supplied archive SHA-256 `5d3d39c7af5e9922db5db7a15a7b12611ddce282b68de7b3135f0aabae315b24`; MIT, copyright 2026 Security Level 5 | README, LICENSE, Cargo manifest and `src/proxy.rs` inspected and hashed in place. No Rust execution or archive/history extraction |

Hades README blob: `6dca36193efecf5ffa8ecccf2c9a059e4f016dfb`. Auditor blob: `aed637957cbb1b669a3e4e9d990ef90bb84b755e`. LICENSE blob: `261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64`.

The installed local skill auditor differed from the reviewed blob and was not executed. An exact public commit copy was fetched with its license into ignored `.local\foundations`, verified, then used against the controlled fixture. No upstream implementation source is vendored into the shipped runtime. Generated `.local\foundation-evidence.json` records the actual review execution and selected archive file hashes.

The gateway is an HTTP/2 CONNECT application-protocol proxy whose decision concerns destination connectivity. Selected source authorizes before connecting and copies bidirectional bytes. It does not authorize individual encrypted tools or reauthorize every byte. Python teaching examples are not used as proof of the Rust network path.

## Reproduce the controlled foundation review

```powershell
.\.venv\Scripts\python.exe tools\review_foundations.py --hades-auditor C:\path\to\reviewed\mcp_manifest_audit.py --gateway-archive C:\path\to\agent-gateway.zip
```

The helper verifies the auditor's exact Git blob before running it, accepts only the frozen synthetic fixture, has a timeout, verifies the archive hash and reads only four allowlisted entries without extraction. `.local\hades-report.json` is importable through the role-gated console. Heuristic output never becomes a permission.

## Dependencies and assets

Exact dependencies are in [the Python lock](../requirements.lock) and [the npm lock](../apps/dashboard/package-lock.json). FastAPI, React, SQLAlchemy, Pydantic, Radix, TanStack Query and the Google SDK retain their upstream package licenses. Wasmtime uses Apache-2.0 WITH LLVM-exception; the local Inter font package includes its OFL notices; Lucide retains its upstream license. The console prebuild collects the installed runtime license text, including the font notice, into `THIRD-PARTY-NOTICES.txt` and serves it beside the assets. Do not remove dependency notices when redistributing built software.

The brand SVG and UI implementation are newly authored. No stock images, private employer data, production financial records or external tracking fonts are used. Choose the new project's own distribution license and obtain organizer reuse approval before public submission; this delivery does not establish hackathon eligibility.

## Official API references consulted

- [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/)
- [React versions](https://react.dev/versions)
- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
- [Wasmtime Python API](https://bytecodealliance.github.io/wasmtime-py/)
- [Radix Dialog accessibility and focus behavior](https://www.radix-ui.com/primitives/docs/components/dialog)
- [SQLAlchemy transaction model](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)

No private project code or credentials were sent to those public documentation services.
