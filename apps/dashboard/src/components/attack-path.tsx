import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  BrainCircuit,
  Database,
  Ghost,
  Globe2,
  LayoutList,
  Lock,
  Maximize2,
  Minus,
  Network,
  Plus,
  Radar,
  ShieldAlert,
  ShieldCheck,
  Unplug,
  Waypoints,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../api";
import { ErrorState, Loading } from "../components";
import { useLens } from "../experience";
import type { AttackNode, AttackPath } from "../types";

const icons: Record<string, LucideIcon> = {
  internet: Globe2,
  agent: Bot,
  endpoint: Network,
  firewall: ShieldAlert,
  database: Database,
  detection: Radar,
  ai: BrainCircuit,
  lock: Lock,
  honeypot: Ghost,
  stop: Unplug,
  shield: ShieldCheck,
};

export function useAttackPath(caseId: string | undefined) {
  return useQuery({
    queryKey: ["attack-path", caseId],
    queryFn: () => api<AttackPath>(`/v1/incidents/${caseId}/attack-path`),
    enabled: !!caseId,
  });
}

const COLUMN = 178;
const ROW = 150;

export function AttackPathGraph({
  path,
  onEvidence,
}: {
  path: AttackPath;
  onEvidence?: (eventId: string) => void;
}) {
  const { plain } = useLens();
  const [zoom, setZoom] = useState(0.92);
  const [layout, setLayout] = useState<"graph" | "list">("graph");
  const [selected, setSelected] = useState<string | null>(null);
  const columns = useMemo(() => {
    const used = [...new Set(path.nodes.map((node) => node.column))].sort((a, b) => a - b);
    return new Map(used.map((column, index) => [column, index]));
  }, [path.nodes]);
  const width = Math.max(columns.size, 1) * COLUMN + 80;
  const height = 3 * ROW + 40;
  const position = (node: AttackNode) => ({
    x: 70 + (columns.get(node.column) ?? 0) * COLUMN,
    y: 70 + node.row * ROW,
  });
  const byId = new Map(path.nodes.map((node) => [node.id, node]));
  const active = selected ? byId.get(selected) : null;
  return (
    <div className="attack-graph">
      <div className="attack-graph-toolbar">
        <div className="attack-graph-modes" role="group" aria-label="Attack path layout">
          <button
            type="button"
            aria-label="Show as list"
            aria-pressed={layout === "list"}
            className={layout === "list" ? "active" : ""}
            onClick={() => setLayout("list")}
          >
            <LayoutList size={15} />
          </button>
          <button
            type="button"
            aria-label="Show as graph"
            aria-pressed={layout === "graph"}
            className={layout === "graph" ? "active" : ""}
            onClick={() => setLayout("graph")}
          >
            <Waypoints size={15} />
          </button>
        </div>
      </div>
      {layout === "list" ? (
        <ol className="attack-flow-list">
          {path.nodes.map((node) => {
            const Icon = icons[node.kind] ?? Network;
            return (
              <li key={node.id} className={`flow-${node.status}`}>
                <span className="flow-icon">
                  <Icon size={16} />
                </span>
                <div>
                  <strong>{plain ? node.label_plain : node.label_technical}</strong>
                  <p>{plain ? node.plain : node.technical}</p>
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="attack-canvas">
          <div className="attack-zoom" role="group" aria-label="Graph zoom">
            <button
              type="button"
              aria-label="Zoom in"
              onClick={() => setZoom((value) => Math.min(1.6, value + 0.15))}
            >
              <Plus size={15} />
            </button>
            <button
              type="button"
              aria-label="Zoom out"
              onClick={() => setZoom((value) => Math.max(0.55, value - 0.15))}
            >
              <Minus size={15} />
            </button>
            <button type="button" aria-label="Fit graph" onClick={() => setZoom(0.92)}>
              <Maximize2 size={14} />
            </button>
          </div>
          <div className="attack-scroll">
            <svg
              viewBox={`0 0 ${width} ${height}`}
              width={width * zoom}
              height={height * zoom}
              role="img"
              aria-label={plain ? path.headline_plain : path.headline_technical}
            >
              <defs>
                <marker
                  id="attack-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto-start-reverse"
                >
                  <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
                </marker>
              </defs>
              {path.edges.map((edge) => {
                const from = byId.get(edge.source);
                const to = byId.get(edge.target);
                if (!from || !to) return null;
                const a = position(from);
                const b = position(to);
                const vertical = Math.abs(a.x - b.x) < 5;
                const mid = (a.x + b.x) / 2;
                const d = vertical
                  ? `M ${a.x} ${a.y + (a.y < b.y ? 72 : -36)} L ${b.x} ${b.y + (a.y < b.y ? -40 : 72)}`
                  : `M ${a.x + 34} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${b.x - 38} ${b.y}`;
                const level = Math.abs(a.y - b.y) < 5;
                return (
                  <g key={edge.id} className={`attack-edge edge-${edge.kind}`}>
                    <path d={d} markerEnd="url(#attack-arrow)" />
                    {(level || vertical) && (
                      <text
                        x={vertical ? a.x + 12 : mid}
                        y={vertical ? (a.y + b.y) / 2 + 4 : a.y - 10}
                        textAnchor={vertical ? "start" : "middle"}
                      >
                        {plain ? edge.plain : edge.technical}
                      </text>
                    )}
                  </g>
                );
              })}
              {path.nodes.map((node) => {
                const Icon = icons[node.kind] ?? Network;
                const { x, y } = position(node);
                const large = node.kind === "internet" || node.kind === "agent";
                const radius = large ? 40 : 30;
                return (
                  <g
                    key={node.id}
                    className={`attack-node node-${node.status} ${selected === node.id ? "selected" : ""}`}
                    transform={`translate(${x} ${y})`}
                    role="button"
                    tabIndex={0}
                    aria-label={`${plain ? node.label_plain : node.label_technical}: ${plain ? node.sub_plain : node.sub_technical}`}
                    onClick={() => setSelected(node.id === selected ? null : node.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelected(node.id === selected ? null : node.id);
                      }
                    }}
                  >
                    <circle r={radius + 6} className="node-halo" />
                    <circle r={radius} className="node-core" />
                    <foreignObject
                      x={-(large ? 18 : 13)}
                      y={-(large ? 18 : 13)}
                      width={large ? 36 : 26}
                      height={large ? 36 : 26}
                    >
                      <Icon size={large ? 36 : 26} strokeWidth={1.6} />
                    </foreignObject>
                    <text y={radius + 24} textAnchor="middle" className="node-label">
                      {plain ? node.label_plain : node.label_technical}
                    </text>
                    <text y={radius + 42} textAnchor="middle" className="node-sub">
                      {(plain ? node.sub_plain : node.sub_technical).slice(0, 34)}
                    </text>
                    {node.badges[0] && (
                      <g transform={`translate(0 ${radius + 58})`} className="node-badge">
                        <rect x={-62} y={-11} width={124} height={20} rx={10} />
                        <text textAnchor="middle" y={4}>
                          {node.badges[0]}
                        </text>
                      </g>
                    )}
                  </g>
                );
              })}
            </svg>
          </div>
          {active && (
            <div className="attack-node-detail" role="status">
              <strong>{plain ? active.label_plain : active.label_technical}</strong>
              <p>{plain ? active.plain : active.technical}</p>
              {!!active.event_ids.length && onEvidence && (
                <div className="evidence-refs">
                  {active.event_ids.slice(0, 6).map((id) => (
                    <button key={id} type="button" onClick={() => onEvidence(id)} title={id}>
                      {id.slice(0, 8)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function AttackStory({ path }: { path: AttackPath }) {
  const { plain } = useLens();
  return (
    <ol className={`attack-story ${plain ? "story-plain" : "story-technical"}`}>
      {path.steps.map((step, index) => (
        <li key={index} className={`story-${step.kind}`}>
          <span className="story-dot" aria-hidden="true" />
          <div>
            <p>
              {plain ? step.plain : step.technical}
              {step.count > 1 && <span className="story-count">×{step.count}</span>}
            </p>
            {step.at && <small>{new Date(step.at).toLocaleTimeString()}</small>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function AttackChain({ path }: { path: AttackPath }) {
  const { plain } = useLens();
  const order = [...path.nodes].sort((a, b) => a.column - b.column || a.row - b.row);
  return (
    <div className="attack-chain" aria-label="Attack chain summary">
      {order.map((node, index) => (
        <span key={node.id} className={`chain-step chain-${node.status}`}>
          {index > 0 && <span className="chain-arrow">→</span>}
          {plain ? node.label_plain : node.label_technical}
        </span>
      ))}
    </div>
  );
}

export function AttackPathSection({
  caseId,
  onEvidence,
}: {
  caseId: string;
  onEvidence?: (eventId: string) => void;
}) {
  const result = useAttackPath(caseId);
  if (result.isPending)
    return <Loading label="Drawing the attack path from recorded evidence..." />;
  if (result.isError)
    return <ErrorState error={result.error} retry={() => void result.refetch()} />;
  return <AttackPathGraph path={result.data} onEvidence={onEvidence} />;
}
