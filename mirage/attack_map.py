"""Live attack map: who sent traffic, what the rules decided and where attackers ended up.

Built only from recorded events, sessions, cases and approvals plus the independent backend
ledger. Counts are observations in the selected window, not predictions or model output.
Attacker-supplied text (snippets, resources, payloads) is never copied into the map.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import httpx
from sqlalchemy import or_, select

from mirage import db, story
from mirage.auth import PrincipalContext
from mirage.common import DomainError, after, now
from mirage.service import Service

WINDOWS = (1, 24, 168, 720)
EVENT_LIMIT = 20000
ATTACKER_LIMIT = 25
FEED_LIMIT = 14
CONTAINED = ("RESTRICTED", "DECOY_PENDING", "DECOY", "TERMINATED")
SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}
DECISIONS = {"allow": "allowed", "require_approval": "approval", "deny": "blocked"}

NODES: dict[str, dict[str, str]] = {
    "external": {
        "tone": "source",
        "label_plain": "Outside agents",
        "label_technical": "External callers",
        "about_plain": "Bots and AI agents from outside the company that called our app.",
        "about_technical": "Sessions owned by external principals; requests enter through the "
        "Layer 7 portal edge.",
    },
    "internal": {
        "tone": "source",
        "label_plain": "Our AI agents",
        "label_technical": "Internal workloads",
        "about_plain": "Our own AI assistants doing day-to-day work.",
        "about_technical": "Sessions owned by internal workload principals calling typed tools "
        "through the dispatcher.",
    },
    "entry": {
        "tone": "gate",
        "label_plain": "Front door checks",
        "label_technical": "L7 ingress · dispatcher",
        "about_plain": "Every request stops here first. Our access rules check who is asking, "
        "what they want to do and on which record.",
        "about_technical": "Server-owned identity, tenant, tool/action and exact-resource policy "
        "evaluation before any dispatch. Route state is checked first: contained sessions never "
        "reach production.",
    },
    "allowed": {
        "tone": "allowed",
        "label_plain": "Allowed",
        "label_technical": "allow",
        "about_plain": "Requests that matched a rule allowing exactly that action.",
        "about_technical": "SCOPED_ALLOW decisions (including approved requests whose digest "
        "matched).",
    },
    "approval": {
        "tone": "approval",
        "label_plain": "Needs approval",
        "label_technical": "require_approval",
        "about_plain": "Risky actions that need a person to say yes before they can happen.",
        "about_technical": "EXACT_APPROVAL_REQUIRED decisions. Approvals bind the exact request "
        "digest, policy version and expiry.",
    },
    "blocked": {
        "tone": "blocked",
        "label_plain": "Blocked",
        "label_technical": "deny",
        "about_plain": "Requests our rules refused. Nothing was sent to real systems.",
        "about_technical": "Deny decisions (explicit deny, no allow rule, out-of-scope resource, "
        "approval mismatch, route blocked). No backend dispatch occurs.",
    },
    "business": {
        "tone": "allowed",
        "label_plain": "Business systems",
        "label_technical": "Synthetic backend",
        "about_plain": "The real business records (synthetic in this lab). Counts come from the "
        "systems' own independent log, not from Mirage.",
        "about_technical": "Independent HMAC-authenticated backend ledger. Native P1 path is "
        "direct signed HTTP; the mTLS CONNECT gateway is proposed and not in this path.",
    },
    "detected": {
        "tone": "detected",
        "label_plain": "Attack spotted",
        "label_technical": "Detection rules",
        "about_plain": "Fixed rules noticed a pattern, such as probing records and then trying "
        "a forbidden action, and opened an issue.",
        "about_technical": "Deterministic, versioned correlation rules (D-001…D-006) over "
        "authenticated decision events. Each match opens one case per session.",
    },
    "ai": {
        "tone": "ai",
        "label_plain": "AI explanation",
        "label_technical": "Advisory AI",
        "about_plain": "AI explains what happened in plain words. It cannot block, allow or "
        "move anyone — the rules do that.",
        "about_technical": "Bounded, schema-validated model analysis with evidence citations. "
        "No tools, credentials or route authority.",
    },
    "limited": {
        "tone": "contain",
        "label_plain": "Access limited",
        "label_technical": "RESTRICTED",
        "about_plain": "The agent was cut off from real data the moment it was flagged.",
        "about_technical": "Restrict-before-diversion: production access is fenced with a new "
        "route version before any decoy is prepared.",
    },
    "honeypot": {
        "tone": "honeypot",
        "label_plain": "Honeypot",
        "label_technical": "DECOY · Wasm",
        "about_plain": "A fake copy of the app that keeps the attacker busy with made-up data "
        "while we watch.",
        "about_technical": "Isolated Wasm decoy with no host capabilities; synthetic, "
        "session-scoped state with TTL and request budgets. Never falls back to production.",
    },
}

EDGES: list[dict[str, str]] = [
    {
        "source": "external",
        "target": "entry",
        "tone": "source",
        "unit": "requests",
        "plain": "requests sent",
        "technical": "HTTP requests",
    },
    {
        "source": "internal",
        "target": "entry",
        "tone": "source",
        "unit": "requests",
        "plain": "requests sent",
        "technical": "typed tool calls",
    },
    {
        "source": "entry",
        "target": "allowed",
        "tone": "allowed",
        "unit": "requests",
        "plain": "allowed",
        "technical": "allow",
    },
    {
        "source": "entry",
        "target": "approval",
        "tone": "approval",
        "unit": "requests",
        "plain": "need approval",
        "technical": "require_approval",
    },
    {
        "source": "entry",
        "target": "blocked",
        "tone": "blocked",
        "unit": "requests",
        "plain": "blocked",
        "technical": "deny",
    },
    {
        "source": "entry",
        "target": "honeypot",
        "tone": "honeypot",
        "unit": "requests",
        "plain": "answered by the honeypot",
        "technical": "decoy route (simulated)",
    },
    {
        "source": "approval",
        "target": "allowed",
        "tone": "approval",
        "unit": "approvals",
        "plain": "approved by a person",
        "technical": "approved / consumed",
    },
    {
        "source": "allowed",
        "target": "business",
        "tone": "allowed",
        "unit": "requests",
        "plain": "reached business systems",
        "technical": "signed backend execution",
    },
    {
        "source": "blocked",
        "target": "detected",
        "tone": "detected",
        "unit": "agents",
        "plain": "pattern spotted",
        "technical": "rule match → case",
    },
    {
        "source": "detected",
        "target": "ai",
        "tone": "ai",
        "unit": "agents",
        "plain": "explained by AI",
        "technical": "advisory analysis",
    },
    {
        "source": "detected",
        "target": "limited",
        "tone": "contain",
        "unit": "agents",
        "plain": "access limited",
        "technical": "RESTRICTED",
    },
    {
        "source": "limited",
        "target": "honeypot",
        "tone": "honeypot",
        "unit": "agents",
        "plain": "moved to the honeypot",
        "technical": "DECOY",
    },
]


def _edge_id(source: str, target: str) -> str:
    return f"{source}-{target}"


class Trace:
    """Records the map nodes and edges one session passed through."""

    def __init__(self, path: set[str], traversed: list[str], counts: Counter[str]) -> None:
        self.path, self.traversed, self.counts = path, traversed, counts

    def walk(self, source: str, target: str, amount: int = 1) -> None:
        self.path.update({source, target})
        identifier = _edge_id(source, target)
        self.traversed.append(identifier)
        self.counts[identifier] += amount


def _contained_at(history: list[dict[str, Any]]) -> str | None:
    return next((entry["at"] for entry in history if entry.get("mode") in CONTAINED), None)


def _top(counter: Counter[str], plain: dict[str, str], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "plain": plain.get(key, key.replace("_", " ").lower()),
            "technical": key,
            "count": count,
        }
        for key, count in counter.most_common(limit)
    ]


def _ledger(service: Service, tenant: str, start: str) -> tuple[list[dict[str, Any]], bool]:
    try:
        snapshot = service.backend.snapshot(tenant)
    except (httpx.HTTPError, DomainError, OSError, ValueError, KeyError):
        return [], False
    effects = [
        item for item in snapshot.get("effects", []) if str(item.get("created_at", "")) >= start
    ]
    return effects, True


def build(service: Service, context: PrincipalContext, hours: int, origin: str) -> dict[str, Any]:
    context.require("analyst")
    if hours not in WINDOWS:
        raise DomainError(400, "INVALID_TIME_RANGE", "Choose 1, 24, 168 or 720 hours")
    tenant = context.tenant_id
    start = after(-hours * 3600)
    filters = [db.events.c.tenant_id == tenant, db.events.c.received_at >= start]
    if origin != "all":
        filters.append(db.events.c.origin == origin)
    approval_filters = [db.approvals.c.tenant_id == tenant, db.approvals.c.created_at >= start]
    with service.db.engine.connect() as connection:
        events = db.rows(
            connection,
            select(
                db.events.c.id,
                db.events.c.session_id,
                db.events.c.event_type,
                db.events.c.outcome,
                db.events.c.received_at,
                db.events.c.body,
            )
            .where(*filters)
            .order_by(db.events.c.sequence.desc())
            .limit(EVENT_LIMIT),
        )
        active_events = select(db.events.c.session_id).where(*filters).distinct()
        active_approvals = select(db.approvals.c.session_id).where(*approval_filters).distinct()
        session_filters = [
            db.sessions.c.tenant_id == tenant,
            or_(db.sessions.c.id.in_(active_events), db.sessions.c.id.in_(active_approvals)),
        ]
        if origin != "all":
            session_filters.append(db.sessions.c.origin == origin)
        sessions = {
            item["id"]: item
            for item in db.rows(
                connection,
                select(
                    db.sessions.c.id,
                    db.sessions.c.principal_id,
                    db.sessions.c.caller_class,
                    db.sessions.c.route_mode,
                    db.sessions.c.history,
                    db.sessions.c.origin,
                ).where(*session_filters),
            )
        }
        cases = {
            item["session_id"]: item
            for item in db.rows(
                connection,
                select(
                    db.incidents.c.id,
                    db.incidents.c.number,
                    db.incidents.c.session_id,
                    db.incidents.c.title,
                    db.incidents.c.severity,
                    db.incidents.c.status,
                    db.incidents.c.rules,
                    db.incidents.c.investigation,
                ).where(
                    db.incidents.c.tenant_id == tenant,
                    or_(
                        db.incidents.c.session_id.in_(active_events),
                        db.incidents.c.session_id.in_(active_approvals),
                    ),
                ),
            )
            if item["session_id"] in sessions
        }
        approvals = [
            item
            for item in db.rows(
                connection,
                select(
                    db.approvals.c.session_id,
                    db.approvals.c.status,
                    db.approvals.c.created_at,
                ).where(*approval_filters),
            )
            if item["session_id"] in sessions
        ]
        names = {
            item["id"]: item["name"]
            for item in db.rows(
                connection,
                select(db.principals.c.id, db.principals.c.name).where(
                    db.principals.c.tenant_id == tenant,
                    db.principals.c.id.in_({item["principal_id"] for item in sessions.values()}),
                ),
            )
        }
        effects, ledger_available = _ledger(service, tenant, start)
        executions = {
            item["id"]: item["session_id"]
            for item in db.rows(
                connection,
                select(db.executions.c.id, db.executions.c.session_id).where(
                    db.executions.c.tenant_id == tenant,
                    db.executions.c.id.in_([item["execution_id"] for item in effects]),
                ),
            )
        }

    per: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "requests": 0,
            "allowed": 0,
            "approval": 0,
            "approval_requests": 0,
            "blocked": 0,
            "simulated": 0,
            "completed": 0,
            "tools": Counter(),
            "first_seen": None,
            "last_seen": None,
        }
    )
    tools: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: Counter[str] = Counter()
    for event in events:
        session = sessions.get(event["session_id"])
        if session is None:
            continue
        stats = per[event["session_id"]]
        attributes = (event["body"] or {}).get("attributes") or {}
        tool = str(attributes.get("tool") or "")[:80]
        seen = event["received_at"]
        stats["first_seen"] = min(stats["first_seen"] or seen, seen)
        stats["last_seen"] = max(stats["last_seen"] or seen, seen)
        if event["event_type"] == "authorization.decided" and event["outcome"] in DECISIONS:
            bucket = DECISIONS[event["outcome"]]
            stats["requests"] += 1
            stats[bucket] += 1
            if tool:
                stats["tools"][tool] += 1
                tools[bucket][tool] += 1
                tools["entry"][tool] += 1
            if bucket == "blocked":
                reasons[str(attributes.get("reason_code") or "UNKNOWN")[:60]] += 1
        elif event["event_type"] == "decoy.observed":
            stats["requests"] += 1
            stats["simulated"] += 1
            if tool:
                stats["tools"][tool] += 1
                tools["honeypot"][tool] += 1
                tools["entry"][tool] += 1
        elif event["event_type"] == "tool.completed" and event["outcome"] == "success":
            stats["completed"] += 1

    approved_sessions: Counter[str] = Counter()
    approval_status: Counter[str] = Counter()
    for item in approvals:
        stats = per[item["session_id"]]
        stats["requests"] += 1
        stats["approval_requests"] += 1
        seen = item["created_at"]
        stats["first_seen"] = min(stats["first_seen"] or seen, seen)
        stats["last_seen"] = max(stats["last_seen"] or seen, seen)
        approval_status[item["status"]] += 1
        if item["status"] in {"approved", "consumed"}:
            approved_sessions[item["session_id"]] += 1

    attributed = [
        item for item in effects if executions.get(str(item.get("execution_id", ""))) in sessions
    ]
    landed: Counter[str] = Counter(executions[str(item["execution_id"])] for item in attributed)

    rows: list[dict[str, Any]] = []
    edge_counts: Counter[str] = Counter()
    source_agents: dict[str, set[str]] = {"external": set(), "internal": set()}
    source_requests: dict[str, Counter[str]] = {"external": Counter(), "internal": Counter()}
    flagged = limited = honeypot = disconnected = reviewed = active_decoys = 0
    flagged_external = 0
    rules: Counter[str] = Counter()
    severities: Counter[str] = Counter()
    for session_id, session in sessions.items():
        stats = per[session_id]
        source = "external" if session["caller_class"] == "external" else "internal"
        modes = [entry.get("mode") for entry in session["history"]]
        case = cases.get(session_id)
        path = {source, "entry"}
        traversed: list[str] = []
        trace = Trace(path, traversed, edge_counts)
        if stats["requests"]:
            trace.walk(source, "entry", stats["requests"])
            source_agents[source].add(session["principal_id"])
            source_requests[source][session["principal_id"]] += stats["requests"]
        for bucket in ("allowed", "blocked"):
            if stats[bucket]:
                trace.walk("entry", bucket, stats[bucket])
        if stats["approval"] + stats["approval_requests"]:
            trace.walk("entry", "approval", stats["approval"] + stats["approval_requests"])
        if stats["simulated"]:
            trace.walk("entry", "honeypot", stats["simulated"])
        if approved_sessions[session_id]:
            trace.walk("approval", "allowed", approved_sessions[session_id])
        reached = landed[session_id] if ledger_available else stats["completed"]
        if reached:
            trace.walk("allowed", "business", reached)
        if case is not None:
            flagged += 1
            flagged_external += source == "external"
            trace.walk("blocked", "detected")
            rules.update(case["rules"] or [])
            severities[case["severity"]] += 1
            if case["investigation"] is not None:
                reviewed += 1
                trace.walk("detected", "ai")
            if "RESTRICTED" in modes:
                trace.walk("detected", "limited")
        if "RESTRICTED" in modes:
            limited += 1
            path.add("limited")
        if "DECOY" in modes:
            honeypot += 1
            trace.walk("limited", "honeypot")
            active_decoys += session["route_mode"] == "DECOY"
        if "TERMINATED" in modes and (case is not None or "RESTRICTED" in modes):
            disconnected += 1
        suspicious = (
            case is not None
            or "RESTRICTED" in modes
            or "DECOY" in modes
            or (source == "external" and stats["blocked"] > 0)
        )
        if not suspicious:
            continue
        top_tool = stats["tools"].most_common(1)[0][0] if stats["tools"] else None
        rows.append(
            {
                "session_id": session_id,
                "principal_id": session["principal_id"],
                "principal_name": names.get(session["principal_id"], session["principal_id"]),
                "caller_class": session["caller_class"],
                "origin": session["origin"],
                "requests": stats["requests"],
                "allowed": stats["allowed"],
                "blocked": stats["blocked"],
                "simulated": stats["simulated"],
                "first_seen": stats["first_seen"],
                "last_seen": stats["last_seen"],
                "route_mode": session["route_mode"],
                "verdict_plain": story.ROUTES.get(session["route_mode"], session["route_mode"]),
                "top_tool": top_tool,
                "top_tool_plain": story.plain_tool(top_tool) if top_tool else None,
                "incident": None
                if case is None
                else {
                    "id": case["id"],
                    "number": case["number"],
                    "title": case["title"],
                    "severity": case["severity"],
                    "status": case["status"],
                    "rules": case["rules"] or [],
                    "rule_plain": story.RULES.get((case["rules"] or [""])[0], case["title"]),
                    "ai_reviewed": case["investigation"] is not None,
                },
                "path": sorted(path),
                "edges": traversed,
            }
        )
    rows = _recent_first(rows)[:ATTACKER_LIMIT]

    reads = sum(not item.get("mutated") for item in attributed)
    changes = sum(bool(item.get("mutated")) for item in attributed)
    after_containment = 0
    flagged_reads = 0
    for item in attributed:
        session = sessions[executions[str(item["execution_id"])]]
        contained_at = _contained_at(session["history"])
        if contained_at is not None and str(item.get("created_at", "")) >= contained_at:
            after_containment += 1
        elif session["id"] in cases:
            flagged_reads += 1

    totals = {
        "requests": sum(stats["requests"] for stats in per.values()),
        "allowed": sum(stats["allowed"] for stats in per.values()),
        "approval": sum(stats["approval"] + stats["approval_requests"] for stats in per.values()),
        "held_for_approval": sum(stats["approval"] for stats in per.values()),
        "approval_requests": sum(stats["approval_requests"] for stats in per.values()),
        "blocked": sum(stats["blocked"] for stats in per.values()),
        "simulated": sum(stats["simulated"] for stats in per.values()),
        "agents": len(source_agents["external"] | source_agents["internal"]),
        "external_agents": len(source_agents["external"]),
        "sessions": len(sessions),
        "flagged": flagged,
        "flagged_external": flagged_external,
        "limited": limited,
        "honeypot": honeypot,
        "active_honeypot": active_decoys,
        "disconnected": disconnected,
        "ai_reviewed": reviewed,
    }
    ledger = {
        "available": ledger_available,
        "actions": len(attributed) if ledger_available else None,
        "reads": reads if ledger_available else None,
        "changes": changes if ledger_available else None,
        "after_containment": after_containment if ledger_available else None,
        "flagged_before_containment": flagged_reads if ledger_available else None,
        "outside_view": len(effects) - len(attributed) if ledger_available else None,
        "source": "independent synthetic backend ledger",
    }
    return {
        "generated_at": now(),
        "hours": hours,
        "origin": origin,
        "profile": service.settings.profile,
        "capped": len(events) == EVENT_LIMIT,
        "totals": totals,
        "ledger": ledger,
        "nodes": _nodes(
            totals,
            ledger,
            source_requests,
            tools,
            reasons,
            rules,
            severities,
            approval_status,
            service.provider.name,
        ),
        "edges": [
            {
                **edge,
                "id": _edge_id(edge["source"], edge["target"]),
                "count": edge_counts[_edge_id(edge["source"], edge["target"])],
            }
            for edge in EDGES
        ],
        "attackers": rows,
        "feed": _feed(
            events,
            sessions,
            names,
            {
                identifier
                for identifier, session in sessions.items()
                if identifier in cases
                or any(entry.get("mode") == "RESTRICTED" for entry in session["history"])
            },
        ),
        "gateway": {
            "state": "proposed",
            "plain": "A network gateway in front of business systems is planned, not active here.",
            "technical": "mTLS HTTP/2 CONNECT gateway is proposed; the native P1 path is direct "
            "signed HTTP. Destination connectivity is not tool authorization.",
        },
    }


def _recent_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable order: severity group first, then most recently active within each group."""
    groups: dict[tuple[bool, int], list[dict[str, Any]]] = defaultdict(list)
    for item in rows:
        key = (
            item["incident"] is None,
            SEVERITY.get((item["incident"] or {}).get("severity", "low"), 4),
        )
        groups[key].append(item)
    ordered: list[dict[str, Any]] = []
    for key in sorted(groups):
        ordered.extend(sorted(groups[key], key=lambda item: item["last_seen"] or "", reverse=True))
    return ordered


def _nodes(
    totals: dict[str, int],
    ledger: dict[str, Any],
    source_requests: dict[str, Counter[str]],
    tools: dict[str, Counter[str]],
    reasons: Counter[str],
    rules: Counter[str],
    severities: Counter[str],
    approval_status: Counter[str],
    provider: str,
) -> list[dict[str, Any]]:
    external_requests = sum(source_requests["external"].values())
    internal_requests = sum(source_requests["internal"].values())

    def fact(plain: str, technical: str, value: Any, tone: str = "") -> dict[str, Any]:
        return {"plain": plain, "technical": technical, "value": value, "tone": tone}

    values: dict[str, dict[str, Any]] = {
        "external": {
            "value": len(source_requests["external"]),
            "unit": "agents",
            "facts": [fact("Requests", "Requests", external_requests)],
            "breakdown": _top(source_requests["external"], {}),
        },
        "internal": {
            "value": len(source_requests["internal"]),
            "unit": "agents",
            "facts": [fact("Requests", "Requests", internal_requests)],
            "breakdown": _top(source_requests["internal"], {}),
        },
        "entry": {
            "value": totals["requests"],
            "unit": "requests",
            "facts": [
                fact("Allowed", "allow", totals["allowed"], "allowed"),
                fact("Waiting for a person", "require_approval", totals["approval"], "approval"),
                fact("Blocked", "deny", totals["blocked"], "blocked"),
                fact("Sent to honeypot", "simulated", totals["simulated"], "honeypot"),
            ],
            "breakdown": _top(tools["entry"], story.TOOLS),
        },
        "allowed": {
            "value": totals["allowed"],
            "unit": "requests",
            "facts": [],
            "breakdown": _top(tools["allowed"], story.TOOLS),
        },
        "approval": {
            "value": totals["approval"],
            "unit": "requests",
            "facts": [
                fact(
                    "Held until a person decides", "require_approval", totals["held_for_approval"]
                ),
                fact("Approval requests", "Approval records", totals["approval_requests"]),
                *(
                    fact(
                        "Approved and used" if status == "consumed" else status.title(),
                        status,
                        count,
                        "allowed" if status in {"approved", "consumed"} else "",
                    )
                    for status, count in sorted(approval_status.items())
                ),
            ],
            "breakdown": _top(tools["approval"], story.TOOLS),
        },
        "blocked": {
            "value": totals["blocked"],
            "unit": "requests",
            "facts": [],
            "breakdown": _top(reasons, story.REASONS),
        },
        "business": {
            "value": ledger["actions"],
            "unit": "actions",
            "facts": [
                fact("Records read", "Reads", ledger["reads"]),
                fact("Records changed", "Mutations", ledger["changes"]),
                fact(
                    "Touched after an attacker was contained",
                    "Effects after containment",
                    ledger["after_containment"],
                    "allowed" if ledger["after_containment"] == 0 else "blocked",
                ),
                fact(
                    "Done by flagged agents before they were caught",
                    "Pre-containment effects by flagged sessions",
                    ledger["flagged_before_containment"],
                ),
                *(
                    [
                        fact(
                            "Not linked to traffic in this view",
                            "Effects outside the current filter",
                            ledger["outside_view"],
                        )
                    ]
                    if ledger["outside_view"]
                    else []
                ),
            ],
            "breakdown": [],
        },
        "detected": {
            "value": totals["flagged"],
            "unit": "agents",
            "facts": [
                fact(level.title(), level, severities[level], level)
                for level in ("critical", "high", "medium", "low")
                if severities[level]
            ],
            "breakdown": _top(rules, story.RULES),
        },
        "ai": {
            "value": totals["ai_reviewed"],
            "unit": "agents",
            "facts": [
                fact(
                    "Issues still unexplained",
                    "Cases without analysis",
                    totals["flagged"] - totals["ai_reviewed"],
                ),
                fact("AI provider", "Provider", provider),
            ],
            "breakdown": [],
        },
        "limited": {
            "value": totals["limited"],
            "unit": "agents",
            "facts": [fact("Disconnected later", "TERMINATED", totals["disconnected"])],
            "breakdown": [],
        },
        "honeypot": {
            "value": totals["honeypot"],
            "unit": "agents",
            "facts": [
                fact("Fake answers served", "Simulated responses", totals["simulated"], "honeypot"),
                fact("Still inside now", "Active decoy sessions", totals["active_honeypot"]),
            ],
            "breakdown": _top(tools["honeypot"], story.TOOLS),
        },
    }
    return [{"id": key, **NODES[key], **values[key]} for key in NODES]


def _feed(
    events: list[dict[str, Any]],
    sessions: dict[str, dict[str, Any]],
    names: dict[str, str],
    flagged: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for event in events:
        if len(items) >= FEED_LIMIT:
            break
        session = sessions.get(event["session_id"])
        if session is None:
            continue
        kind = event["event_type"]
        attributes = (event["body"] or {}).get("attributes") or {}
        tool = str(attributes.get("tool") or "")[:80] or None
        reason = str(attributes.get("reason_code") or "")[:60] or None
        name = names.get(session["principal_id"], session["principal_id"])
        who = ("Outside agent " if session["caller_class"] == "external" else "Internal agent ") + (
            f"“{name}”"
        )
        action = story.plain_tool(tool)
        if kind == "authorization.decided" and event["outcome"] in DECISIONS:
            tone = DECISIONS[event["outcome"]]
            plain = {
                "allowed": f"{who} was allowed to {action}",
                "approval": f"{who} asked to {action} — waiting for a person",
                "blocked": f"{who} tried to {action} — blocked: {story.plain_reason(reason)}",
            }[tone]
            technical = f"authorization.decided {event['outcome']} {tool or '-'} {reason or ''}"
        elif kind == "decoy.observed":
            tone = "honeypot"
            plain = f"{who} tried to {action} — the honeypot answered with fake data"
            technical = f"decoy.observed simulated {tool or '-'}"
        elif kind == "session.transitioned":
            mode = str((event["body"] or {}).get("route_mode") or "")
            if mode == "TERMINATED" and event["session_id"] not in flagged:
                continue
            tone = {"DECOY": "honeypot", "TERMINATED": "blocked"}.get(mode, "contain")
            plain = f"{who}: {story.ROUTES.get(mode, mode)}"
            technical = f"session.transitioned → {mode} ({reason or 'no reason'})"
        else:
            continue
        items.append(
            {
                "id": event["id"],
                "at": event["received_at"],
                "session_id": event["session_id"],
                "caller_class": session["caller_class"],
                "tone": tone,
                "plain": plain,
                "technical": f"{technical.strip()} · {session['principal_id']} · "
                f"session {event['session_id'][:8]}",
            }
        )
    return items
