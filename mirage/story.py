"""Deterministic attack-path stories built only from recorded case evidence."""

from __future__ import annotations

from typing import Any

TOOLS = {
    "supplier.lookup": "look up a supplier record",
    "invoice.compare": "compare invoices",
    "payment.change_request": "change a supplier's bank details",
    "customer.export": "export the whole customer list",
    "infrastructure.delete": "delete company infrastructure",
}
REASONS = {
    "EXPLICIT_DENY": "that action is forbidden for everyone",
    "NO_ALLOW_RULE": "no rule allows it to do that",
    "RESOURCE_OUT_OF_SCOPE": "it is not allowed to see that record",
    "EXACT_APPROVAL_REQUIRED": "a person must approve it first",
    "SCOPED_ALLOW": "it was allowed to do this",
    "APPROVAL_VERIFICATION_FAILED": "its approval did not match the request",
    "DELEGATION_ESCALATION": "it tried to give a helper more power than it has",
    "VERIFIED_SYNTHETIC_INTERACTION": "it used the fake honeypot system",
    "ROUTE_BLOCKED": "its access had already been limited",
    "PROHIBITED_TOOL": "that action is forbidden",
}
RULES = {
    "D-001": "Kept asking for many records it may not see",
    "D-002": "Probed records, then tried a forbidden action",
    "D-003": "Used an approval that did not match the request",
    "D-004": "Tried to give itself more power",
    "D-005": "Touched the honeypot bait",
    "D-006": "Hidden instructions plus a forbidden action",
}
ROUTES = {
    "PRODUCTION": "Normal access",
    "RESTRICTED": "Access limited — real data blocked",
    "DECOY_PENDING": "Preparing the honeypot",
    "DECOY": "Inside the honeypot (fake environment)",
    "TERMINATED": "Disconnected",
}
RESPONSES = {
    "monitor": "keep watching",
    "review": "have a person review it",
    "restrict": "limit its access",
    "consider_deception": "keep it in the honeypot",
}


def plain_tool(tool: str | None) -> str:
    return TOOLS.get(tool or "", tool or "make a request")


def plain_reason(reason: str | None) -> str:
    return REASONS.get(reason or "", (reason or "recorded").replace("_", " ").lower())


def _short(value: str) -> str:
    return value[:8]


def build(detail: dict[str, Any]) -> dict[str, Any]:
    incident, events, session = detail["incident"], detail["events"], detail["session"]
    external = session["caller_class"] == "external"
    actor = incident["principal_id"]
    decisions = [item for item in events if item["event_type"] == "authorization.decided"]
    denied = [item for item in decisions if item["outcome"] == "deny"]
    allowed = [item for item in decisions if item["outcome"] == "allow"]
    honeypot_events = [
        item
        for item in events
        if item["outcome"] == "simulated" or item["event_type"] == "decoy.observed"
    ]
    modes = [entry["mode"] for entry in session["history"]]
    restricted = "RESTRICTED" in modes
    in_honeypot = "DECOY" in modes
    terminated = "TERMINATED" in modes
    effects = detail.get("backend_outcomes") or []
    investigation = detail.get("investigation")
    who_plain = "An outside AI agent" if external else "An internal AI agent"
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node(identifier: str, kind: str, column: int, row: int, **values: Any) -> None:
        nodes.append(
            {
                "id": identifier,
                "kind": kind,
                "column": column,
                "row": row,
                "badges": [],
                "event_ids": [],
                **values,
            }
        )

    def edge(source: str, target: str, plain: str, technical: str, kind: str) -> None:
        edges.append(
            {
                "id": f"{source}-{target}",
                "source": source,
                "target": target,
                "plain": plain,
                "technical": technical,
                "kind": kind,
            }
        )

    node(
        "source",
        "internet" if external else "agent",
        0,
        1,
        label_plain="Internet" if external else "Internal agent",
        label_technical=actor,
        sub_plain=f"{who_plain} ({actor})",
        sub_technical=f"caller_class={session['caller_class']} · session {_short(session['id'])}",
        plain=f"{who_plain} connected to our systems.",
        technical=f"Principal {actor}; session {session['id']} created in PRODUCTION.",
        status="source",
    )
    node(
        "entry",
        "endpoint",
        1,
        1,
        label_plain="Procurement app",
        label_technical="Application endpoint",
        sub_plain="Where its requests arrived",
        sub_technical="Layer 7 API · tool dispatcher",
        plain="Its requests reached our procurement app, where every action is checked.",
        technical="HTTP/JSON tool invocations evaluated by the deterministic policy engine.",
        status="info",
    )
    edge("source", "entry", "sent requests", "HTTPS tool invocation", "attack")
    if denied:
        targets = sorted(
            {
                f"{item['body']['attributes'].get('resource') or '?'}"
                for item in denied
                if item["body"]["attributes"].get("resource")
            }
        )
        reasons = sorted({item["body"]["attributes"].get("reason_code") or "" for item in denied})
        node(
            "guardrail",
            "firewall",
            2,
            0,
            label_plain="Access rules",
            label_technical="Policy decision point",
            sub_plain=f"Blocked {len(denied)} request{'s' if len(denied) != 1 else ''}",
            sub_technical=f"{len(denied)} deny · {', '.join(filter(None, reasons))}",
            plain=(
                f"Our access rules blocked {len(denied)} request"
                f"{'s' if len(denied) != 1 else ''} because "
                + "; ".join(plain_reason(reason) for reason in reasons if reason)
                + "."
            ),
            technical=(
                f"authorization.decided outcome=deny ×{len(denied)}; resources: "
                + (", ".join(targets[:8]) or "n/a")
            ),
            status="blocked",
            badges=[f"Blocked ×{len(denied)}"],
            event_ids=[item["id"] for item in denied[:20]],
        )
        edge("entry", "guardrail", "checked every action", "policy evaluate()", "attack")
    if allowed:
        node(
            "business",
            "database",
            2,
            2,
            label_plain="Real business system",
            label_technical="Signed synthetic backend",
            sub_plain=f"Answered {len(allowed)} allowed request{'s' if len(allowed) != 1 else ''}",
            sub_technical=f"{len(allowed)} allow · {len(effects)} linked backend executions",
            plain=(
                "Some requests were allowed by the rules and answered normally"
                + (" before anything looked suspicious." if restricted else ".")
            ),
            technical=f"authorization.decided outcome=allow ×{len(allowed)}; executions {len(effects)}.",
            status="allowed",
            event_ids=[item["id"] for item in allowed[:20]],
        )
        edge("entry", "business", "allowed requests", "SCOPED_ALLOW → dispatch", "safe")
    if incident["rules"]:
        node(
            "detection",
            "detection",
            3,
            0,
            label_plain="Behaviour spotted",
            label_technical="Detection rules",
            sub_plain=RULES.get(incident["rules"][0], "Suspicious pattern"),
            sub_technical=" + ".join(incident["rules"]),
            plain="We recognised an attack pattern: "
            + "; ".join(RULES.get(rule, rule).lower() for rule in incident["rules"])
            + ".",
            technical="Deterministic correlation matched "
            + ", ".join(incident["rules"])
            + f" (confidence {incident['confidence']}).",
            status="detected",
            badges=[f"{incident['severity'].capitalize()} risk"],
        )
        edge(
            "guardrail" if denied else "entry",
            "detection",
            "pattern recognised",
            "rule match",
            "attack",
        )
    if investigation:
        node(
            "ai",
            "ai",
            3,
            2,
            label_plain="AI review",
            label_technical=investigation.get("provider", "AI"),
            sub_plain=f"Suggests: {RESPONSES.get(investigation['recommended_response'], 'review')}",
            sub_technical=(
                f"{investigation['recommended_response']} · {investigation['confidence']} confidence"
            ),
            plain="AI read the evidence and explained it. It can only advise; it cannot change access.",
            technical=f"Advisory investigation v{investigation['case_version']}; no tools or authority.",
            status="ai",
            badges=["Advisory only"],
        )
        if incident["rules"]:
            edge("detection", "ai", "explained by AI", "advisory analysis", "info")
    previous = "detection" if incident["rules"] else ("guardrail" if denied else "entry")
    if restricted:
        node(
            "limit",
            "lock",
            4,
            0,
            label_plain="Access limited",
            label_technical="RESTRICTED",
            sub_plain="Real data cut off",
            sub_technical="route fence advanced",
            plain="We immediately cut it off from real data.",
            technical="Session route PRODUCTION → RESTRICTED (monotonic fence).",
            status="contained",
        )
        edge(previous, "limit", "access limited", "PRODUCTION → RESTRICTED", "contain")
        previous = "limit"
    if in_honeypot:
        node(
            "honeypot",
            "honeypot",
            5,
            0,
            label_plain="Honeypot",
            label_technical="Isolated Wasm decoy",
            sub_plain=f"Fake data shown {len(honeypot_events)} time{'s' if len(honeypot_events) != 1 else ''}",
            sub_technical=f"DECOY · {len(honeypot_events)} simulated responses",
            plain=(
                "We quietly moved it into a fake copy of the system (a honeypot). "
                "Everything it sees there is fake."
            ),
            technical="DECOY_PENDING → DECOY; no-import Wasmtime supplier template, synthetic state only.",
            status="honeypot",
            badges=["Honeypot"],
            event_ids=[item["id"] for item in honeypot_events[:20]],
        )
        edge(previous, "honeypot", "moved to honeypot", "DECOY_PENDING → DECOY", "divert")
        previous = "honeypot"
    if terminated:
        node(
            "ended",
            "stop",
            5,
            2 if in_honeypot else 0,
            label_plain="Disconnected",
            label_technical="TERMINATED",
            sub_plain="Session ended",
            sub_technical="route terminal state",
            plain="The session was then ended. It can never return to normal access.",
            technical="Route → TERMINATED; terminal and irreversible.",
            status="ended",
        )
        edge(previous, "ended", "disconnected", "→ TERMINATED", "contain")
    protected = not effects and not allowed
    node(
        "data",
        "shield",
        4,
        2,
        label_plain="Real company data",
        label_technical="Production-like records",
        sub_plain="Not touched" if protected else "Allowed reads only",
        sub_technical="0 linked backend executions"
        if protected
        else f"{len(effects)} linked backend executions",
        plain=(
            "None of our real data was touched by this agent."
            if protected
            else "Only requests the rules allowed reached real data; blocked requests never did."
        ),
        technical=(
            "Independent backend ledger shows no executions linked to this session."
            if protected
            else "Backend ledger links only allowed executions to this session."
        ),
        status="protected",
        badges=["Protected" if protected else "Allowed reads"],
    )
    if denied:
        edge("guardrail", "data", "never reached", "deny before dispatch", "blocked")
    steps = timeline(events, incident)
    if in_honeypot:
        headline = (
            f"{who_plain} kept probing records it was not allowed to see. Our rules blocked it, "
            "recognised the behaviour and moved it into a honeypot (fake system)."
        )
    elif restricted:
        headline = f"{who_plain} was blocked and its access was limited after suspicious behaviour."
    elif denied:
        headline = f"{who_plain} tried actions it was not allowed to do and was blocked."
    else:
        headline = f"{who_plain} triggered a review: {RULES.get(incident['rules'][0], 'pattern')}."
    headline += " No real data was touched." if protected else ""
    return {
        "case_id": incident["id"],
        "number": incident["number"],
        "headline_plain": headline,
        "headline_technical": (
            f"{incident['number']} · {' + '.join(incident['rules'])} · {len(denied)} deny / "
            f"{len(allowed)} allow · route {session['route_mode']} v{session['route_version']} · "
            f"{len(effects)} linked backend executions"
        ),
        "verdict": {
            "external": external,
            "blocked": len(denied),
            "allowed": len(allowed),
            "contained": restricted or in_honeypot or terminated,
            "in_honeypot": in_honeypot,
            "real_data_touched": not protected,
            "route_plain": ROUTES.get(session["route_mode"], session["route_mode"]),
            "route_technical": f"{session['route_mode']} v{session['route_version']}",
        },
        "rules": [{"id": rule, "plain": RULES.get(rule, rule)} for rule in incident["rules"]],
        "nodes": nodes,
        "edges": edges,
        "steps": steps,
        "source": "Deterministic story generated from recorded events; not AI output.",
    }


def timeline(events: list[dict[str, Any]], incident: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    detected = False
    for event in events:
        attributes = event["body"]["attributes"]
        tool, resource, reason = (
            attributes.get("tool"),
            attributes.get("resource"),
            attributes.get("reason_code"),
        )
        technical = (
            f"{event['event_type']} outcome={event['outcome']}"
            + (f" tool={tool}" if tool else "")
            + (f" resource={resource}" if resource else "")
            + (f" reason={reason}" if reason else "")
            + f" route={event['body']['route_mode']}"
        )
        kind = "info"
        if event["event_type"] == "session.transitioned":
            mode = event["body"]["route_mode"]
            if mode == "RESTRICTED" and not detected and incident["rules"]:
                steps.append(
                    {
                        "plain": "We recognised the behaviour: "
                        + "; ".join(RULES.get(rule, rule).lower() for rule in incident["rules"]),
                        "technical": "Correlation matched " + ", ".join(incident["rules"]),
                        "kind": "detected",
                        "event_ids": [],
                        "count": 1,
                    }
                )
                detected = True
            plain = {
                "RESTRICTED": "We cut it off from real data",
                "DECOY_PENDING": "We prepared a fake environment (honeypot)",
                "DECOY": "We moved it into the honeypot",
                "TERMINATED": "We disconnected it",
            }.get(mode, ROUTES.get(mode, mode))
            kind = "honeypot" if mode in {"DECOY", "DECOY_PENDING"} else "contained"
        elif event["event_type"] == "authorization.decided":
            target = f" ({resource})" if resource else ""
            if event["outcome"] == "deny":
                plain = f"It tried to {plain_tool(tool)}{target} → blocked: {plain_reason(reason)}"
                kind = "blocked"
            elif event["outcome"] == "require_approval":
                plain = f"It asked to {plain_tool(tool)}{target} → waiting for a person to approve"
                kind = "approval"
            else:
                plain = f"It asked to {plain_tool(tool)}{target} → allowed"
                kind = "allowed"
        elif event["outcome"] == "simulated" or event["event_type"] == "decoy.observed":
            plain = "It used the honeypot and received fake data (it cannot tell)"
            kind = "honeypot"
        elif event["event_type"] == "request.observed":
            if not attributes.get("snippet") and any(step["kind"] == "traffic" for step in steps):
                continue
            plain = (
                "It sent text that tried to override our instructions"
                if attributes.get("snippet")
                else "Traffic arrived at our app"
            )
            kind = "traffic"
        elif event["event_type"] == "tool.completed":
            plain = f"An allowed action finished: {plain_tool(tool)}"
            kind = "allowed"
        elif event["event_type"] == "gateway.decided":
            plain = f"The network gateway {'blocked' if event['outcome'] == 'deny' else 'allowed'} a connection"
            kind = "blocked" if event["outcome"] == "deny" else "allowed"
        else:
            plain = f"Recorded: {event['event_type'].replace('.', ' ')}"
        previous = steps[-1] if steps else None
        if previous and previous["plain"] == plain and previous["kind"] == kind:
            previous["count"] += 1
            previous["event_ids"].append(event["id"])
            continue
        steps.append(
            {
                "plain": plain,
                "technical": technical,
                "kind": kind,
                "event_ids": [event["id"]],
                "count": 1,
                "at": event["received_at"],
            }
        )
    if incident["rules"] and not detected:
        steps.append(
            {
                "plain": "We recognised the behaviour: "
                + "; ".join(RULES.get(rule, rule).lower() for rule in incident["rules"]),
                "technical": "Correlation matched " + ", ".join(incident["rules"]),
                "kind": "detected",
                "event_ids": [],
                "count": 1,
            }
        )
    return steps[:60]
