import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  BrainCircuit,
  CircleCheck,
  Database,
  DoorOpen,
  Ghost,
  Globe2,
  Hand,
  Lock,
  Maximize2,
  Minus,
  Pause,
  Play,
  Plus,
  Radar,
  ShieldCheck,
  ShieldX,
  TriangleAlert,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../api";
import { Badge, Button, EvidenceDrawer, ErrorState, Loading, Status, ago } from "../components";
import { useLens } from "../experience";
import type {
  EventRecord,
  LiveAttackMap as MapData,
  MapAttacker,
  MapEdge,
  MapNode,
} from "../types";
import { IssueDrawer, SeverityPill } from "./issue-panel";

const WIDTH = 1010;
const HEIGHT = 548;
const CARD_W = 168;
const CARD_H = 66;
const GATE = { x: 270, top: 40, bottom: 512, width: 40 };
const GATE_ENTRY: Record<string, number> = { external: 256, internal: 300 };
const POSITIONS: Record<string, { x: number; y: number }> = {
  external: { x: 100, y: 196 },
  internal: { x: 100, y: 352 },
  allowed: { x: 448, y: 88 },
  approval: { x: 448, y: 224 },
  blocked: { x: 448, y: 360 },
  business: { x: 676, y: 88 },
  ai: { x: 676, y: 224 },
  detected: { x: 676, y: 360 },
  limited: { x: 904, y: 360 },
  honeypot: { x: 904, y: 486 },
};
const ICONS: Record<string, LucideIcon> = {
  external: Globe2,
  internal: Bot,
  entry: DoorOpen,
  allowed: ShieldCheck,
  approval: Hand,
  blocked: ShieldX,
  business: Database,
  detected: Radar,
  ai: BrainCircuit,
  limited: Lock,
  honeypot: Ghost,
};
const COLUMNS = [
  { x: 100, plain: "Who", technical: "Source" },
  { x: GATE.x, plain: "Check", technical: "L7" },
  { x: 448, plain: "Decision", technical: "Policy decision" },
  { x: 676, plain: "What happened", technical: "Effect · detection" },
  { x: 904, plain: "Response", technical: "Route control" },
];
const RANGES = [
  { hours: 1, label: "1h" },
  { hours: 24, label: "24h" },
  { hours: 168, label: "7d" },
  { hours: 720, label: "30d" },
] as const;
const UNITS: Record<string, { plain: [string, string]; technical: [string, string] }> = {
  agents: { plain: ["agent", "agents"], technical: ["session", "sessions"] },
  requests: { plain: ["request", "requests"], technical: ["request", "requests"] },
  approvals: { plain: ["approval", "approvals"], technical: ["approval", "approvals"] },
  actions: {
    plain: ["action done", "actions done"],
    technical: ["ledger effect", "ledger effects"],
  },
};

function unitWord(unit: string, value: number | null, plain: boolean) {
  const words = UNITS[unit]?.[plain ? "plain" : "technical"] ?? [unit, unit];
  return value === 1 ? words[0] : words[1];
}

function plural(value: number, word: string) {
  return `${value} ${word}${value === 1 ? "" : "s"}`;
}

function compact(value: number) {
  if (value < 1000) return String(value);
  if (value < 10000) return `${(value / 1000).toFixed(1)}k`;
  return `${Math.round(value / 1000)}k`;
}

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function activate(event: KeyboardEvent, action: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
}

function geometry(edge: MapEdge) {
  const half = CARD_W / 2;
  if (edge.target === "entry") {
    const from = POSITIONS[edge.source];
    const x1 = from.x + half;
    const x2 = GATE.x - GATE.width / 2;
    const y2 = GATE_ENTRY[edge.source] ?? (GATE.top + GATE.bottom) / 2;
    const middle = (x1 + x2) / 2;
    return {
      d: `M ${x1} ${from.y} C ${middle} ${from.y}, ${middle} ${y2}, ${x2} ${y2}`,
      label: { x: middle, y: (from.y + y2) / 2 },
      long: false,
    };
  }
  if (edge.source === "entry") {
    const to = POSITIONS[edge.target];
    const x1 = GATE.x + GATE.width / 2;
    const x2 = to.x - half;
    return {
      d: `M ${x1} ${to.y} L ${x2} ${to.y}`,
      label: { x: edge.target === "honeypot" ? 560 : (x1 + x2) / 2, y: to.y },
      long: edge.target === "honeypot",
    };
  }
  const a = POSITIONS[edge.source];
  const b = POSITIONS[edge.target];
  if (Math.abs(a.x - b.x) < 2) {
    const down = b.y > a.y;
    const y1 = a.y + (down ? CARD_H / 2 : -CARD_H / 2);
    const y2 = b.y + (down ? -CARD_H / 2 : CARD_H / 2);
    return { d: `M ${a.x} ${y1} L ${b.x} ${y2}`, label: { x: a.x, y: (y1 + y2) / 2 }, long: false };
  }
  const x1 = a.x + half;
  const x2 = b.x - half;
  return { d: `M ${x1} ${a.y} L ${x2} ${b.y}`, label: { x: (x1 + x2) / 2, y: a.y }, long: false };
}

function edgeSentence(edge: MapEdge, plain: boolean) {
  const unit = unitWord(edge.unit, edge.count, plain);
  return plain
    ? `${edge.count} ${unit}: ${edge.plain}`
    : `${edge.technical} × ${edge.count} ${unit}`;
}

type Focus = { session: MapAttacker; step: number } | null;

export function LiveAttackMap() {
  const { plain } = useLens();
  const [hours, setHours] = useState<number>(168);
  const [origin, setOrigin] = useState<"all" | "live" | "laboratory">("all");
  const [live, setLive] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>(null);
  const [zoom, setZoom] = useState(1);
  const [issue, setIssue] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EventRecord | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const reduced = prefersReducedMotion();
  const result = useQuery({
    queryKey: ["attack-map", hours, origin],
    queryFn: () => api<MapData>(`/v1/attack-map?hours=${hours}&origin=${origin}`),
    refetchInterval: live ? 10_000 : false,
    refetchOnWindowFocus: live,
  });
  const playing = !!focus && focus.step < focus.session.edges.length;
  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(
      () => setFocus((value) => (value ? { ...value, step: value.step + 1 } : value)),
      650,
    );
    return () => window.clearTimeout(timer);
  }, [playing, focus]);
  const data = result.data;
  const attackers = data?.attackers;
  useEffect(() => {
    if (!focus || !attackers) return;
    const fresh = attackers.find((item) => item.session_id === focus.session.session_id);
    if (!fresh) setFocus(null);
    else if (fresh !== focus.session) setFocus({ session: fresh, step: focus.step });
  }, [attackers, focus]);
  const nodes = useMemo(
    () => new Map((data?.nodes ?? []).map((node) => [node.id, node])),
    [data?.nodes],
  );
  if (result.isPending)
    return <Loading label="Building the live attack map from recorded traffic..." />;
  if (result.isError || !data)
    return <ErrorState error={result.error} retry={() => void result.refetch()} />;

  const replay = (session: MapAttacker) => {
    setSelected(null);
    setFocus({ session, step: reduced ? session.edges.length : 0 });
    const stage = stageRef.current;
    if (stage) {
      const box = stage.getBoundingClientRect();
      if (box.top < 0 || box.top > window.innerHeight * 0.5)
        stage.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
    }
  };
  const hotEdges = focus ? new Set(focus.session.edges.slice(0, focus.step)) : null;
  const hotNodes = focus
    ? new Set(
        focus.step === 0
          ? [focus.session.path.find((item) => item === "external" || item === "internal")]
          : focus.session.edges.slice(0, focus.step).flatMap((id) => {
              const edge = data.edges.find((item) => item.id === id);
              return edge ? [edge.source, edge.target] : [];
            }),
      )
    : null;
  const maxima = data.edges.reduce<Record<string, number>>((value, edge) => {
    value[edge.unit] = Math.max(value[edge.unit] ?? 0, edge.count);
    return value;
  }, {});
  const width = (edge: MapEdge) =>
    edge.count === 0 ? 1.25 : 2 + 5.5 * Math.sqrt(edge.count / Math.max(1, maxima[edge.unit] ?? 1));
  const entry = nodes.get("entry");
  const totals = data.totals;
  const ledger = data.ledger;
  const label = (node: MapNode) => (plain ? node.label_plain : node.label_technical);
  const valueText = (node: MapNode) => (node.value === null ? "—" : compact(node.value));
  const unitText = (node: MapNode) => unitWord(node.unit, node.value, plain);
  const badge = (id: string): { text: string; tone: string } | null => {
    if (id === "business") {
      if (!ledger.available)
        return { text: plain ? "Log unavailable" : "Ledger unavailable", tone: "neutral" };
      return ledger.after_containment === 0
        ? {
            text: plain ? "✓ Attackers changed nothing" : "0 effects after containment",
            tone: "allowed",
          }
        : {
            text: `${ledger.after_containment} after containment`,
            tone: "blocked",
          };
    }
    if (id === "honeypot" && totals.simulated > 0)
      return {
        text: plain
          ? `${compact(totals.simulated)} fake answers`
          : `${compact(totals.simulated)} simulated`,
        tone: "honeypot",
      };
    return null;
  };
  const select = (id: string) => {
    setFocus(null);
    setSelected((value) => (value === id ? null : id));
  };
  const range = RANGES.find((item) => item.hours === hours)?.label ?? `${hours}h`;
  const blockedRate = totals.requests ? Math.round((totals.blocked * 100) / totals.requests) : 0;
  const describe = plain
    ? `${totals.requests} requests checked, ${totals.blocked} blocked, ${totals.flagged} attackers spotted, ${totals.honeypot} moved to the honeypot.`
    : `${totals.requests} decisions; deny ${totals.blocked}; cases ${totals.flagged}; DECOY sessions ${totals.honeypot}.`;

  return (
    <section className="live-map" aria-labelledby="live-map-title">
      <div className="live-map-head">
        <div>
          <h2 id="live-map-title">{plain ? "Live attack traffic" : "Live L7 traffic flow"}</h2>
          <p>
            {plain
              ? "Every request goes left to right: who sent it, what our rules decided, and where attackers ended up."
              : "Recorded decisions, detections and route transitions for the selected window. Counts are observations, not model output."}
          </p>
        </div>
        <div className="live-map-controls">
          <div className="map-range" role="group" aria-label="Time range">
            {RANGES.map((item) => (
              <button
                key={item.hours}
                type="button"
                aria-pressed={hours === item.hours}
                className={hours === item.hours ? "active" : ""}
                onClick={() => setHours(item.hours)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <select
            aria-label="Traffic source"
            value={origin}
            onChange={(event) => setOrigin(event.target.value as typeof origin)}
          >
            <option value="all">All traffic</option>
            <option value="live">Live only</option>
            <option value="laboratory">Lab only</option>
          </select>
          <button
            type="button"
            className={`map-live ${live ? "on" : ""}`}
            aria-pressed={live}
            onClick={() => setLive((value) => !value)}
            title={live ? "Pause auto-refresh and flow animation" : "Resume auto-refresh"}
          >
            {live ? <span className="map-live-dot" aria-hidden="true" /> : <Pause size={13} />}
            {live ? "Live" : "Paused"}
          </button>
        </div>
      </div>

      <div className="map-kpis" role="list" aria-label="Attack map summary">
        <Kpi
          tone="neutral"
          label={plain ? "Requests checked" : "Decisions"}
          value={compact(totals.requests)}
          sub={`${plural(totals.agents, plain ? "agent" : "principal")} · last ${range}`}
        />
        <Kpi
          tone="blocked"
          label="Blocked"
          value={compact(totals.blocked)}
          sub={`${blockedRate}% of requests`}
        />
        <Kpi
          tone="detected"
          label={plain ? "Attackers spotted" : "Sessions with cases"}
          value={compact(totals.flagged)}
          sub={`${totals.flagged_external} from outside`}
        />
        <Kpi
          tone="honeypot"
          label={plain ? "Moved to honeypot" : "DECOY sessions"}
          value={compact(totals.honeypot)}
          sub={`${compact(totals.simulated)} ${plain ? "fake answers" : "simulated responses"}`}
        />
        <Kpi
          tone={
            ledger.available ? (ledger.after_containment === 0 ? "allowed" : "blocked") : "neutral"
          }
          label={plain ? "Real data touched after catch" : "Effects after containment"}
          value={ledger.available ? String(ledger.after_containment) : "—"}
          sub={
            ledger.available
              ? plain
                ? "Independent log check"
                : ledger.source
              : "Ledger unavailable"
          }
          icon={ledger.available && ledger.after_containment === 0 ? CircleCheck : undefined}
        />
        <Kpi
          tone="ai"
          label={plain ? "Explained by AI" : "AI-analysed cases"}
          value={`${totals.ai_reviewed}/${totals.flagged}`}
          sub={plain ? "AI explains, rules decide" : "Advisory only · no authority"}
        />
      </div>

      <div ref={stageRef} className={`map-stage ${focus || selected ? "has-inspector" : ""}`}>
        <div className={`map-canvas ${live && !reduced ? "animate" : ""}`}>
          <div className="map-scroll">
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              style={{
                width: `${zoom * 100}%`,
                maxWidth: `${Math.round(WIDTH * 1.1 * zoom)}px`,
                minWidth: `${Math.round(740 * zoom)}px`,
              }}
              role="group"
              aria-label={describe}
            >
              <defs>
                {[
                  "source",
                  "allowed",
                  "approval",
                  "blocked",
                  "detected",
                  "ai",
                  "contain",
                  "honeypot",
                ].map((tone) => (
                  <marker
                    key={tone}
                    id={`map-arrow-${tone}`}
                    viewBox="0 0 10 10"
                    refX="8.5"
                    refY="5"
                    markerWidth="9"
                    markerHeight="9"
                    markerUnits="userSpaceOnUse"
                    orient="auto"
                  >
                    <path d="M0 0 L10 5 L0 10 z" className={`map-arrow tone-${tone}`} />
                  </marker>
                ))}
              </defs>
              {COLUMNS.map((column) => (
                <text key={column.x} x={column.x} y={22} textAnchor="middle" className="map-column">
                  {(plain ? column.plain : column.technical).toUpperCase()}
                </text>
              ))}
              {data.edges.map((edge) => {
                const shape = geometry(edge);
                const hot = hotEdges?.has(edge.id);
                const dim = hotEdges ? !hot : false;
                return (
                  <g
                    key={edge.id}
                    className={`map-edge tone-${edge.tone} ${edge.count ? "" : "idle"} ${hot ? "is-hot" : ""} ${dim ? "is-dim" : ""}`}
                  >
                    <title>{edgeSentence(edge, plain)}</title>
                    {hot && (
                      <path
                        d={shape.d}
                        className="map-edge-glow"
                        style={{ strokeWidth: width(edge) + 8 }}
                      />
                    )}
                    <path
                      d={shape.d}
                      className="map-edge-line"
                      style={{ strokeWidth: width(edge) }}
                      markerEnd={edge.count ? `url(#map-arrow-${edge.tone})` : undefined}
                    />
                    {edge.count > 0 && (
                      <path
                        d={shape.d}
                        className="map-edge-flow"
                        style={{ strokeWidth: Math.max(1.6, width(edge) * 0.42) }}
                      />
                    )}
                  </g>
                );
              })}
              <g
                className={`map-gate ${selected === "entry" ? "is-selected" : ""} ${hotNodes && !hotNodes.has("entry") ? "is-dim" : ""}`}
                role="button"
                tabIndex={0}
                aria-pressed={selected === "entry"}
                aria-label={`${compact(entry?.value ?? 0)} ${entry ? label(entry) : "Front door checks"}`}
                onClick={() => select("entry")}
                onKeyDown={(event) => activate(event, () => select("entry"))}
              >
                <rect
                  x={GATE.x - GATE.width / 2}
                  y={GATE.top}
                  width={GATE.width}
                  height={GATE.bottom - GATE.top}
                  rx={GATE.width / 2}
                  className="map-gate-band"
                />
                <DoorOpen
                  x={GATE.x - 9}
                  y={GATE.top + 12}
                  width={18}
                  height={18}
                  className="map-gate-icon"
                />
                <text x={GATE.x} y={GATE.top + 50} textAnchor="middle" className="map-gate-count">
                  {compact(entry?.value ?? 0)}{" "}
                </text>
                <text
                  transform={`translate(${GATE.x + 4} ${(GATE.top + GATE.bottom) / 2 + 36}) rotate(-90)`}
                  textAnchor="middle"
                  className="map-gate-label"
                >
                  {entry ? label(entry).toUpperCase() : "FRONT DOOR"}
                </text>
              </g>
              {data.edges
                .filter((edge) => edge.count > 0)
                .map((edge) => {
                  const shape = geometry(edge);
                  const text = shape.long
                    ? plain
                      ? `${compact(edge.count)} sent to honeypot`
                      : `DECOY route × ${compact(edge.count)}`
                    : compact(edge.count);
                  const pill = Math.max(26, text.length * 7 + 14);
                  const dim = hotEdges ? !hotEdges.has(edge.id) : false;
                  return (
                    <g
                      key={`${edge.id}-pill`}
                      className={`map-pill tone-${edge.tone} ${dim ? "is-dim" : ""}`}
                      transform={`translate(${shape.label.x} ${shape.label.y})`}
                    >
                      <title>{edgeSentence(edge, plain)}</title>
                      <rect x={-pill / 2} y={-11} width={pill} height={22} rx={11} />
                      <text y={4.5} textAnchor="middle">
                        {text}
                      </text>
                    </g>
                  );
                })}
              {data.nodes
                .filter((node) => POSITIONS[node.id])
                .map((node) => {
                  const position = POSITIONS[node.id];
                  const Icon = ICONS[node.id] ?? Radar;
                  const active = selected === node.id;
                  const dim = hotNodes ? !hotNodes.has(node.id) : false;
                  const extra = badge(node.id);
                  const badgeWidth = extra ? extra.text.length * 6.6 + 20 : 0;
                  return (
                    <g
                      key={node.id}
                      className={`map-node tone-${node.tone} ${active ? "is-selected" : ""} ${dim ? "is-dim" : ""} ${hotNodes?.has(node.id) ? "is-hot" : ""}`}
                      transform={`translate(${position.x - CARD_W / 2} ${position.y - CARD_H / 2})`}
                      role="button"
                      tabIndex={0}
                      aria-pressed={active}
                      aria-label={`${label(node)} ${valueText(node)} ${unitText(node)}${extra ? ` ${extra.text}` : ""}`}
                      onClick={() => select(node.id)}
                      onKeyDown={(event) => activate(event, () => select(node.id))}
                    >
                      <rect width={CARD_W} height={CARD_H} rx={14} className="map-card" />
                      <rect
                        x={0}
                        y={16}
                        width={3.5}
                        height={CARD_H - 32}
                        rx={1.75}
                        className="map-card-accent"
                      />
                      <Icon x={14} y={11} width={16} height={16} className="map-card-icon" />
                      <text x={37} y={24} className="map-card-label">
                        {label(node)}{" "}
                      </text>
                      <text x={14} y={52} className="map-card-value">
                        {valueText(node)}{" "}
                        <tspan dx={1} className="map-card-unit">
                          {unitText(node)}{" "}
                        </tspan>
                      </text>
                      {extra && (
                        <g
                          transform={`translate(${CARD_W / 2} ${CARD_H + 16})`}
                          className={`map-badge tone-${extra.tone}`}
                        >
                          <rect
                            x={-badgeWidth / 2}
                            y={-10.5}
                            width={badgeWidth}
                            height={21}
                            rx={10.5}
                          />
                          <text y={4} textAnchor="middle">
                            {extra.text}
                          </text>
                        </g>
                      )}
                    </g>
                  );
                })}
            </svg>
          </div>
          {totals.requests === 0 && (
            <div className="map-empty" role="status">
              <strong>
                {plain ? "No traffic in this time range" : "No recorded decisions in window"}
              </strong>
              <span>
                Pick a longer range, or run a lab scenario from{" "}
                <Link to="/overview">Risk overview</Link>.
              </span>
            </div>
          )}
          <MapLegend plain={plain} zoom={zoom} onZoom={setZoom} />
        </div>
        {(focus || selected) && (
          <aside className="map-inspector" aria-label="Attack map details">
            {focus ? (
              <SessionDetail
                attacker={focus.session}
                plain={plain}
                playing={playing}
                onReplay={() => replay(focus.session)}
                onOpen={(id) => setIssue(id)}
                onClose={() => setFocus(null)}
                nodes={nodes}
              />
            ) : (
              selected &&
              nodes.get(selected) && (
                <NodeDetail
                  node={nodes.get(selected)!}
                  data={data}
                  plain={plain}
                  onClose={() => setSelected(null)}
                  onFocus={replay}
                />
              )
            )}
          </aside>
        )}
      </div>
      <p className="map-footnote">
        {plain ? data.gateway.plain : data.gateway.technical}{" "}
        {data.capped &&
          (plain ? "Showing the newest 20,000 records." : "Event scan capped at 20,000.")}
      </p>

      <div className="map-lower">
        <AttackerTable
          attackers={data.attackers}
          plain={plain}
          focused={focus?.session.session_id ?? null}
          onReplay={replay}
          onOpen={(id) => setIssue(id)}
        />
        <LiveFeed
          data={data}
          plain={plain}
          onFocus={(sessionId) => {
            const match = data.attackers.find((item) => item.session_id === sessionId);
            if (match) replay(match);
          }}
        />
      </div>
      <IssueDrawer caseId={issue} onClose={() => setIssue(null)} onEvidence={setEvidence} />
      <EvidenceDrawer event={evidence} onClose={() => setEvidence(null)} />
    </section>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub: string;
  tone: string;
  icon?: LucideIcon;
}) {
  return (
    <div className={`map-kpi tone-${tone}`} role="listitem">
      <span className="map-kpi-label">{label}</span>
      <strong>
        {Icon && <Icon size={18} aria-hidden="true" />}
        {value}
      </strong>
      <small>{sub}</small>
    </div>
  );
}

function MapLegend({
  plain,
  zoom,
  onZoom,
}: {
  plain: boolean;
  zoom: number;
  onZoom: (value: number) => void;
}) {
  const items = [
    ["allowed", plain ? "Allowed" : "allow"],
    ["approval", plain ? "Needs a person" : "require_approval"],
    ["blocked", plain ? "Blocked" : "deny"],
    ["detected", plain ? "Spotted" : "detection"],
    ["honeypot", plain ? "Honeypot" : "decoy"],
    ["ai", plain ? "AI (advice only)" : "advisory AI"],
  ];
  return (
    <div className="map-legend">
      <div className="map-legend-items" role="group" aria-label="Legend">
        {items.map(([tone, text]) => (
          <span key={tone}>
            <i className={`tone-${tone}`} aria-hidden="true" />
            {text}
          </span>
        ))}
      </div>
      <span className="map-legend-note">
        {plain ? "Line thickness = amount of traffic" : "Stroke width ∝ √count per unit"}
      </span>
      <div className="map-zoom" role="group" aria-label="Map zoom">
        <button
          type="button"
          aria-label="Zoom out"
          disabled={zoom <= 0.8}
          onClick={() => onZoom(Math.max(0.8, +(zoom - 0.2).toFixed(2)))}
        >
          <Minus size={14} />
        </button>
        <button type="button" aria-label="Fit map" onClick={() => onZoom(1)}>
          <Maximize2 size={13} />
        </button>
        <button
          type="button"
          aria-label="Zoom in"
          disabled={zoom >= 1.6}
          onClick={() => onZoom(Math.min(1.6, +(zoom + 0.2).toFixed(2)))}
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  );
}

function NodeDetail({
  node,
  data,
  plain,
  onClose,
  onFocus,
}: {
  node: MapNode;
  data: MapData;
  plain: boolean;
  onClose: () => void;
  onFocus: (attacker: MapAttacker) => void;
}) {
  const Icon = ICONS[node.id] ?? Radar;
  const peak = Math.max(1, ...node.breakdown.map((item) => item.count));
  const through = data.attackers.filter((item) => item.path.includes(node.id)).slice(0, 5);
  const unit = unitWord(node.unit, node.value, plain);
  const incoming = data.edges.filter((edge) => edge.target === node.id && edge.count > 0);
  const outgoing = data.edges.filter((edge) => edge.source === node.id && edge.count > 0);
  return (
    <div className={`map-detail tone-${node.tone}`}>
      <header>
        <span className="map-detail-icon">
          <Icon size={20} />
        </span>
        <div>
          <span className="map-detail-kicker">{plain ? "Step on the map" : node.id}</span>
          <h3>{plain ? node.label_plain : node.label_technical}</h3>
        </div>
        <button
          type="button"
          className="map-detail-close"
          aria-label="Close details"
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </header>
      <p className="map-detail-value">
        <strong>{node.value === null ? "—" : node.value}</strong> {unit}
      </p>
      <p>{plain ? node.about_plain : node.about_technical}</p>
      {!!node.facts.length && (
        <dl className="map-facts">
          {node.facts.map((item) => (
            <div
              key={item.technical}
              className={`${item.tone ? `tone-${item.tone}` : ""} ${typeof item.value === "string" ? "map-fact-wide" : ""}`}
            >
              <dt>{plain ? item.plain : item.technical}</dt>
              <dd>{item.value ?? "—"}</dd>
            </div>
          ))}
        </dl>
      )}
      {!!node.breakdown.length && (
        <div className="map-breakdown">
          <h4>
            {node.id === "blocked"
              ? plain
                ? "Why requests were blocked"
                : "reason_code"
              : node.id === "detected"
                ? plain
                  ? "What was spotted"
                  : "Rules matched"
                : node.id === "external" || node.id === "internal"
                  ? plain
                    ? "Busiest agents"
                    : "Principals by requests"
                  : plain
                    ? "What they tried to do"
                    : "Tools"}
          </h4>
          <ul>
            {node.breakdown.map((item) => (
              <li key={item.key}>
                <span>{plain ? item.plain : item.technical}</span>
                <b>{item.count}</b>
                <i style={{ width: `${(item.count * 100) / peak}%` }} aria-hidden="true" />
              </li>
            ))}
          </ul>
        </div>
      )}
      {(!!incoming.length || !!outgoing.length) && (
        <div className="map-flows">
          <h4>{plain ? "Traffic through this step" : "Edges"}</h4>
          <ul>
            {[...incoming, ...outgoing].map((edge) => (
              <li key={edge.id} className={`tone-${edge.tone}`}>
                {edgeSentence(edge, plain)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!through.length && (
        <div className="map-through">
          <h4>{plain ? "Attackers that passed here" : "Flagged sessions on this node"}</h4>
          <ul>
            {through.map((item) => (
              <li key={item.session_id}>
                <button type="button" onClick={() => onFocus(item)}>
                  <span>{item.principal_name}</span>
                  <small>
                    {item.incident?.number ?? item.session_id.slice(0, 8)} ·{" "}
                    {plain ? item.verdict_plain : item.route_mode}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SessionDetail({
  attacker,
  plain,
  playing,
  nodes,
  onReplay,
  onOpen,
  onClose,
}: {
  attacker: MapAttacker;
  plain: boolean;
  playing: boolean;
  nodes: Map<string, MapNode>;
  onReplay: () => void;
  onOpen: (id: string) => void;
  onClose: () => void;
}) {
  const order = [
    "external",
    "internal",
    "entry",
    "allowed",
    "approval",
    "blocked",
    "business",
    "detected",
    "ai",
    "limited",
    "honeypot",
  ];
  const steps = order.filter((id) => attacker.path.includes(id));
  return (
    <div className="map-detail tone-blocked">
      <header>
        <span className="map-detail-icon">
          {attacker.caller_class === "external" ? <Globe2 size={20} /> : <Bot size={20} />}
        </span>
        <div>
          <span className="map-detail-kicker">
            {attacker.caller_class === "external"
              ? plain
                ? "Outside agent"
                : "caller_class=external"
              : plain
                ? "Internal agent"
                : "caller_class=internal"}
          </span>
          <h3>{attacker.principal_name}</h3>
        </div>
        <button
          type="button"
          className="map-detail-close"
          aria-label="Close path"
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </header>
      <div className="map-session-status">
        <Status value={attacker.route_mode} />
        {attacker.incident && <SeverityPill value={attacker.incident.severity} />}
        {attacker.origin === "laboratory" && <Badge tone="neutral">Lab</Badge>}
      </div>
      <ol
        className="map-path-chips"
        aria-label={plain ? "Path through the map" : "Traversed nodes"}
      >
        {steps.map((id) => {
          const node = nodes.get(id);
          return (
            <li key={id} className={`tone-${node?.tone ?? "neutral"}`}>
              {node ? (plain ? node.label_plain : node.label_technical) : id}
            </li>
          );
        })}
      </ol>
      <dl className="map-facts">
        <div>
          <dt>{plain ? "Requests" : "Requests"}</dt>
          <dd>{attacker.requests}</dd>
        </div>
        <div className="tone-blocked">
          <dt>{plain ? "Blocked" : "deny"}</dt>
          <dd>{attacker.blocked}</dd>
        </div>
        <div className="tone-allowed">
          <dt>{plain ? "Allowed" : "allow"}</dt>
          <dd>{attacker.allowed}</dd>
        </div>
        <div className="tone-honeypot">
          <dt>{plain ? "Fake answers received" : "simulated"}</dt>
          <dd>{attacker.simulated}</dd>
        </div>
        <div className="map-fact-wide">
          <dt>{plain ? "Mostly tried to" : "Top tool"}</dt>
          <dd>{(plain ? attacker.top_tool_plain : attacker.top_tool) ?? "—"}</dd>
        </div>
        <div className="map-fact-wide">
          <dt>{plain ? "Last seen" : "last_seen"}</dt>
          <dd>{ago(attacker.last_seen)}</dd>
        </div>
      </dl>
      {attacker.incident && (
        <p className="map-session-rule">
          <TriangleAlert size={15} aria-hidden="true" />
          <span>
            <strong>{attacker.incident.number}</strong>{" "}
            {plain
              ? attacker.incident.rule_plain
              : `${attacker.incident.rules.join(", ")} · ${attacker.incident.title}`}
          </span>
        </p>
      )}
      <div className="map-session-actions">
        <Button onClick={onReplay} disabled={playing}>
          <Play size={14} />
          {playing ? "Replaying…" : plain ? "Replay path" : "Replay"}
        </Button>
        {attacker.incident && (
          <Button variant="primary" onClick={() => onOpen(attacker.incident!.id)}>
            {plain ? "Open issue" : `Open ${attacker.incident.number}`}
          </Button>
        )}
      </div>
    </div>
  );
}

function AttackerTable({
  attackers,
  plain,
  focused,
  onReplay,
  onOpen,
}: {
  attackers: MapAttacker[];
  plain: boolean;
  focused: string | null;
  onReplay: (attacker: MapAttacker) => void;
  onOpen: (id: string) => void;
}) {
  return (
    <div className="map-card-panel map-attackers">
      <header>
        <h3>{plain ? "Who is attacking" : "Flagged and suspicious sessions"}</h3>
        <span>{attackers.length}</span>
      </header>
      {attackers.length === 0 ? (
        <p className="map-muted">
          {plain
            ? "No suspicious agents in this time range."
            : "No sessions with cases, denials from external callers or non-production routes."}
        </p>
      ) : (
        <div className="map-table-scroll">
          <table>
            <thead>
              <tr>
                <th>{plain ? "Agent" : "Principal"}</th>
                <th>{plain ? "Activity" : "Requests"}</th>
                <th>{plain ? "Spotted as" : "Case"}</th>
                <th>{plain ? "Where it is now" : "route_mode"}</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {attackers.map((item) => (
                <tr
                  key={item.session_id}
                  className={focused === item.session_id ? "is-focused" : ""}
                >
                  <td>
                    <span className="map-agent">
                      {item.caller_class === "external" ? (
                        <Globe2 size={15} aria-label="Outside agent" />
                      ) : (
                        <Bot size={15} aria-label="Internal agent" />
                      )}
                      <span>
                        <strong>{item.principal_name}</strong>
                        <small>
                          {plain
                            ? ago(item.last_seen)
                            : `${item.principal_id} · ${item.session_id.slice(0, 8)}`}
                        </small>
                      </span>
                    </span>
                  </td>
                  <td>
                    <span className="map-activity">
                      <b>{item.requests}</b>
                      <small>
                        {item.blocked} {plain ? "blocked" : "deny"}
                        {item.simulated > 0 && ` · ${item.simulated} ${plain ? "fake" : "sim"}`}
                      </small>
                    </span>
                  </td>
                  <td>
                    {item.incident ? (
                      <span className="map-case">
                        <SeverityPill value={item.incident.severity} />
                        <small>
                          {plain ? item.incident.rule_plain : item.incident.rules.join(", ")}
                        </small>
                      </span>
                    ) : (
                      <small className="map-muted">{plain ? "Not yet" : "—"}</small>
                    )}
                  </td>
                  <td>
                    <Status value={item.route_mode} />
                  </td>
                  <td className="map-row-actions">
                    <button
                      type="button"
                      onClick={() => onReplay(item)}
                      aria-label={`${plain ? "Show path" : "Trace"} for ${item.principal_name} ${item.session_id.slice(0, 8)}`}
                    >
                      {plain ? "Show path" : "Trace"}
                    </button>
                    {item.incident && (
                      <button
                        type="button"
                        onClick={() => onOpen(item.incident!.id)}
                        aria-label={`Open issue ${item.incident.number}`}
                      >
                        {item.incident.number}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LiveFeed({
  data,
  plain,
  onFocus,
}: {
  data: MapData;
  plain: boolean;
  onFocus: (sessionId: string) => void;
}) {
  const known = new Set(data.attackers.map((item) => item.session_id));
  return (
    <div className="map-card-panel map-feed">
      <header>
        <h3>{plain ? "What just happened" : "Recent events"}</h3>
        <small>{ago(data.generated_at)}</small>
      </header>
      {data.feed.length === 0 ? (
        <p className="map-muted">
          {plain ? "Nothing recorded yet." : "No decision events in window."}
        </p>
      ) : (
        <ol>
          {data.feed.map((item) => {
            const content = (
              <>
                <i className={`tone-${item.tone}`} aria-hidden="true" />
                <span>
                  {plain ? item.plain : item.technical}
                  <small>{ago(item.at)}</small>
                </span>
              </>
            );
            return (
              <li key={item.id}>
                {known.has(item.session_id) ? (
                  <button type="button" onClick={() => onFocus(item.session_id)}>
                    {content}
                  </button>
                ) : (
                  <div>{content}</div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
