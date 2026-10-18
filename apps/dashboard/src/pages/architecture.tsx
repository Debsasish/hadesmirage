import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Bot,
  Boxes,
  Database,
  Ghost,
  Globe2,
  Layers3,
  LockKeyhole,
  Network,
  ShieldCheck,
  Waypoints,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../api";
import { Badge, ErrorState, KeyValue, Loading, PageHeading, Panel, Status } from "../components";
import { LiveAttackMap } from "../components/live-attack-map";
import { useLens } from "../experience";
import { useMe } from "../state";
import type { Topology } from "../types";

const icons: Record<string, LucideIcon> = {
  external: Globe2,
  ingress: ShieldCheck,
  application: Layers3,
  agents: Bot,
  dispatcher: LockKeyhole,
  backend: Database,
  gateway: Network,
  soc: Activity,
  router: Waypoints,
  decoy: Ghost,
};

export function ArchitecturePage() {
  const { plain } = useLens();
  const me = useMe();
  return (
    <div className="page attack-map-page">
      <PageHeading
        eyebrow="LIVE TRAFFIC / TRUST BOUNDARIES"
        title="Attack map"
        description={
          plain
            ? "See who is sending requests, what our rules did, and how attackers were moved into the honeypot."
            : "Recorded L7 decisions, detections and route transitions, followed by the implemented component topology."
        }
        actions={me.data ? <Badge tone="neutral">{me.data.profile}</Badge> : undefined}
      />
      <LiveAttackMap />
      <SystemArchitecture />
    </div>
  );
}

function SystemArchitecture() {
  const result = useQuery({
    queryKey: ["architecture"],
    queryFn: () => api<Topology>("/v1/architecture"),
  });
  const [selection, setSelection] = useState<{ kind: "node" | "edge"; id: string }>({
    kind: "node",
    id: "ingress",
  });
  if (result.isPending) return <Loading label="Loading the implemented topology..." />;
  if (result.isError) return <ErrorState error={result.error} />;
  const data = result.data;
  const node =
    selection.kind === "node" ? data.nodes.find((item) => item.id === selection.id) : undefined;
  const edge =
    selection.kind === "edge" ? data.edges.find((item) => item.id === selection.id) : undefined;
  const Icon = node ? (icons[node.id] ?? Boxes) : Waypoints;
  return (
    <section className="system-architecture" aria-labelledby="system-architecture-title">
      <header className="system-architecture-head">
        <div>
          <h2 id="system-architecture-title">System architecture</h2>
          <p>
            Select a component or connection. Proposed paths are never presented as verified
            traffic.
          </p>
        </div>
        <Badge tone="neutral">{data.profile}</Badge>
      </header>
      <div className="architecture-note">
        <Layers3 size={19} />
        <span>
          <strong>Primarily Layer 7.</strong> Application identity, tools, resources and request
          routing. Supporting network controls are a separate boundary.
        </span>
      </div>
      <div className="architecture-grid">
        <Panel
          className="topology-panel"
          title="Implemented local topology"
          subtitle="Solid: configured native path / dashed: proposed gateway integration"
          action={<span className="small muted">{data.recorded_events} recorded events</span>}
        >
          <div className="topology-scroll">
            <div className="topology">
              <div className="topology-zone zone-production">
                <span>Production-like / synthetic records</span>
              </div>
              <div className="topology-zone zone-control">
                <span>Trusted control plane</span>
              </div>
              <div className="topology-zone zone-deception">
                <span>Deception / no host capabilities</span>
              </div>
              <svg
                viewBox="0 0 1000 600"
                preserveAspectRatio="none"
                className="topology-edges"
                aria-label="Selectable connections"
              >
                <defs>
                  <marker
                    id="edge-arrow"
                    viewBox="0 0 8 8"
                    refX="7"
                    refY="4"
                    markerWidth="5"
                    markerHeight="5"
                    orient="auto"
                  >
                    <path d="M0 0 L8 4 L0 8" fill="var(--edge)" />
                  </marker>
                </defs>
                {data.edges.map((item) => {
                  const from = data.nodes.find((value) => value.id === item.source);
                  const to = data.nodes.find((value) => value.id === item.target);
                  if (!from || !to) return null;
                  const x1 = from.x * 10,
                    y1 = from.y * 6,
                    x2 = to.x * 10,
                    y2 = to.y * 6;
                  const path =
                    item.id === "dispatcher-backend"
                      ? `M ${x1 + 65} ${y1 + 10} C 460 415, 710 415, ${x2 - 65} ${y2 + 10}`
                      : `M ${x1} ${y1} L ${x2} ${y2}`;
                  return (
                    <g
                      key={item.id}
                      className={`topology-edge ${item.state === "proposed" ? "proposed" : ""} ${selection.id === item.id ? "edge-selected" : ""}`}
                    >
                      <path d={path} markerEnd="url(#edge-arrow)" />
                      <path
                        d={path}
                        className="edge-hit"
                        role="button"
                        tabIndex={0}
                        aria-label={`Inspect ${item.source} to ${item.target}: ${item.protocol}`}
                        onClick={() => setSelection({ kind: "edge", id: item.id })}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setSelection({ kind: "edge", id: item.id });
                          }
                        }}
                      />
                    </g>
                  );
                })}
              </svg>
              {data.nodes.map((item) => {
                const NodeIcon = icons[item.id] ?? Boxes;
                return (
                  <button
                    key={item.id}
                    className={`topology-node plane-${item.plane} ${selection.id === item.id ? "node-selected" : ""}`}
                    style={{ left: `${item.x}%`, top: `${item.y}%` }}
                    onClick={() => setSelection({ kind: "node", id: item.id })}
                    aria-pressed={selection.id === item.id}
                  >
                    <span>
                      <NodeIcon size={21} strokeWidth={1.6} />
                    </span>
                    <strong>{item.name}</strong>
                    <small>
                      {item.status === "not-configured"
                        ? "PROPOSED / UNCONFIGURED"
                        : item.osi.split(" \u00b7")[0]}
                    </small>
                  </button>
                );
              })}
            </div>
          </div>
          <p className="native-path-label">P1 direct signed HTTP / no P3 claim</p>
          <div className="topology-legend">
            <span>
              <i className="legend-dot teal" />
              Enforcement
            </span>
            <span>
              <i className="legend-dot blue" />
              Synthetic application
            </span>
            <span>
              <i className="legend-dot purple" />
              Isolated deception
            </span>
            <span>
              <i className="legend-dashed" />
              Proposed, unverified
            </span>
          </div>
        </Panel>
        <Panel className="topology-detail">
          <div className="panel-body">
            <span
              className={`topology-detail-icon ${node?.plane === "deception" ? "purple" : "teal"}`}
            >
              <Icon size={28} />
            </span>
            <div className="object-context">Selected {node ? "component" : "connection"}</div>
            <h2>{node?.name ?? `${edge?.source} to ${edge?.target}`}</h2>
            <Status value={node?.status ?? edge?.state ?? "unknown"} />
            <p>{node?.role ?? edge?.detail}</p>
            {node && (
              <dl className="detail-list">
                <KeyValue label="Control placement">{node.osi}</KeyValue>
                <KeyValue label="Trust zone">{node.plane}</KeyValue>
                <KeyValue label="Identity requirement">{node.identity}</KeyValue>
                <KeyValue label="Connected paths">
                  {data.edges
                    .filter((item) => item.source === node.id || item.target === node.id)
                    .map((item) => (
                      <button
                        key={item.id}
                        className="edge-detail-link"
                        onClick={() => setSelection({ kind: "edge", id: item.id })}
                      >
                        {item.source}
                        <ArrowRight size={11} />
                        {item.target}
                        <ArrowUpRight size={11} />
                      </button>
                    ))}
                </KeyValue>
              </dl>
            )}
            {edge && (
              <dl className="detail-list">
                <KeyValue label="Protocol">{edge.protocol}</KeyValue>
                <KeyValue label="Evidence state">{edge.state}</KeyValue>
                <KeyValue label="Profile">{data.profile}</KeyValue>
              </dl>
            )}
            <div className="callout">
              <ShieldCheck size={17} />
              <div>
                The diagram describes implemented boundaries and separately labeled proposals. It
                does not certify every network path.
              </div>
            </div>
          </div>
        </Panel>
      </div>
      <div className="osi-grid">
        <Panel>
          <div className="panel-body">
            <Badge tone="teal" dot={false}>
              L7 / PRIMARY
            </Badge>
            <h2>Understand the operation</h2>
            <p>
              HTTP/API identity, tool and action permission, exact resource scope, session routing,
              and synthetic responses.
            </p>
          </div>
        </Panel>
        <Panel>
          <div className="panel-body">
            <Badge tone="blue" dot={false}>
              L3 + L4 / SUPPORTING
            </Badge>
            <h2>Constrain connectivity</h2>
            <p>
              Segmentation, IP/port destinations and direct-path bypass prevention belong to a
              separately tested deployment profile.
            </p>
          </div>
        </Panel>
        <Panel>
          <div className="panel-body">
            <Badge tone="neutral" dot={false}>
              TLS / IDENTITY & ENCRYPTION
            </Badge>
            <h2>Identity is not authority</h2>
            <p>
              Certificate-bound connectivity is not tool authorization. Application session tracking
              does not make Mirage a Layer 5 appliance.
            </p>
          </div>
        </Panel>
      </div>
    </section>
  );
}
