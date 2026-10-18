# Editable architecture diagrams

All diagrams describe P1-native and explicitly label unimplemented P2/P3 paths.

| Diagram | Editable source | Rendered SVG |
| --- | --- | --- |
| System context | [Source](01-context.mmd) | [SVG](01-context.svg) |
| Native deployment | [Source](02-deployment.mmd) | [SVG](02-deployment.svg) |
| Trust and capability boundary | [Source](03-trust-boundaries.mmd) | [SVG](03-trust-boundaries.svg) |
| Protected execution | [Source](04-internal-execution.mmd) | [SVG](04-internal-execution.svg) |
| Restriction and diversion | [Source](05-external-diversion.mmd) | [SVG](05-external-diversion.svg) |
| Session state | [Source](06-session-state.mmd) | [SVG](06-session-state.svg) |
| Persistent data | [Source](07-data-model.mmd) | [SVG](07-data-model.svg) |
| OSI placement | [Source](08-osi-controls.mmd) | [SVG](08-osi-controls.svg) |
| Failure and recovery | [Source](09-failure-recovery.mmd) | [SVG](09-failure-recovery.svg) |

After installing dashboard dependencies and Chromium, run from `apps\dashboard`:

```powershell
node tools\render-diagrams.mjs
```

The renderer starts an owned loopback-only Vite shell, loads the locally installed Mermaid module, uses strict rendering with no external content, writes these SVGs and stops the browser/server.
