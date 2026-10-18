import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Copy, FileSearch, Maximize2, Search, ShieldCheck } from "lucide-react";
import { api, queryString } from "../api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Loading,
  Modal,
  Status,
  Tabs,
  ago,
  time,
} from "../components";
import { useAction, useWorkspace } from "../state";
import type { CaseDetail, EventRecord, Incident, Page } from "../types";
import { RouteLens } from "./route-lens";

function InvestigationPane({
  identifier,
  onEvidence,
}: {
  identifier: string | undefined;
  onEvidence: (event: EventRecord) => void;
}) {
  const { autoRefresh } = useWorkspace();
  const [tab, setTab] = useState("summary");
  const [inspectedVersion, setInspectedVersion] = useState<number | null>(null);
  const [focused, setFocused] = useState(false);
  const detail = useQuery({
    queryKey: ["case-peek", identifier],
    queryFn: () => api<CaseDetail>(`/v1/incidents/${identifier}`),
    enabled: !!identifier,
    refetchInterval: autoRefresh ? 20_000 : false,
    refetchOnWindowFocus: autoRefresh,
    refetchOnReconnect: autoRefresh,
  });
  const copy = useAction(
    (reference: string) => navigator.clipboard.writeText(reference),
    "Case reference copied.",
  );
  if (!identifier)
    return (
      <aside className="case-peek">
        <Empty
          title="Select a case to investigate"
          description="Its summary, linked evidence and recorded route will open here without leaving the queue."
        />
      </aside>
    );
  if (detail.isPending)
    return (
      <aside className="case-peek">
        <Loading label="Reading case evidence..." />
      </aside>
    );
  if (detail.isError)
    return (
      <aside className="case-peek">
        <ErrorState error={detail.error} retry={() => void detail.refetch()} />
      </aside>
    );
  const { incident, session, events, backend_outcomes } = detail.data;
  return (
    <aside className="case-peek" id="selected-case" aria-label={`Case preview ${incident.number}`}>
      <header className="inspector-heading">
        <span>
          <FileSearch size={16} />
          Investigation
        </span>
        <Badge dot={false}>{incident.number}</Badge>
        <Button
          variant="ghost"
          aria-label="Copy case reference"
          title="Copy case reference"
          busy={copy.isPending}
          onClick={() => copy.mutate(incident.number)}
        >
          <Copy size={14} />
        </Button>
      </header>
      <div className="inspector-title">
        <h3>{incident.title}</h3>
        <div className="inspector-status">
          <Status value={incident.severity} />
          <Status value={session.route_mode} />
        </div>
        <p>{incident.principal_id}</p>
      </div>
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "summary", label: "Summary" },
          { value: "evidence", label: "Evidence" },
          { value: "route", label: "Route" },
        ]}
      />
      <div className="inspector-body">
        {tab === "summary" ? (
          <>
            <p className="inspector-summary">{incident.summary}</p>
            <dl className="inspector-facts">
              <div>
                <dt>Rule confidence</dt>
                <dd>{incident.confidence}</dd>
              </div>
              <div>
                <dt>Application</dt>
                <dd>Procurement Workspace</dd>
              </div>
              <div>
                <dt>Evidence source</dt>
                <dd>
                  {incident.origin === "laboratory"
                    ? "Recorded lab execution"
                    : "Direct application evidence"}
                </dd>
              </div>
              <div>
                <dt>Linked observations</dt>
                <dd>
                  {events.length}
                  {events.length === 500 ? "+" : ""}
                </dd>
              </div>
              <div>
                <dt>Latest received route</dt>
                <dd>
                  {session.route_mode} / v{session.route_version}
                </dd>
              </div>
            </dl>
            <div className="inspector-rules">
              <h4>Matched rules</h4>
              <div>
                {incident.rules.map((rule) => (
                  <Badge key={rule} dot={false} tone="blue">
                    {rule}
                  </Badge>
                ))}
              </div>
            </div>
            <div className="inspector-outcome">
              <ShieldCheck size={18} />
              <div>
                <strong>
                  {backend_outcomes.length
                    ? `${backend_outcomes.length} linked backend execution${backend_outcomes.length === 1 ? "" : "s"}`
                    : "No linked backend execution"}
                </strong>
                <p>
                  {backend_outcomes.length
                    ? backend_outcomes.map((outcome) => outcome.state).join(", ")
                    : "No confirmed effect is linked to this case. This is not a claim about uninstrumented traffic."}
                </p>
              </div>
            </div>
          </>
        ) : tab === "evidence" ? (
          <>
            <div className="inspector-section-title">
              <strong>Linked observations</strong>
              <span>{events.length} recorded</span>
            </div>
            <p className="inspector-disclaimer">
              Authenticated metadata. Untrusted text. Select any record to inspect it.
            </p>
            <div className="inspector-events">
              {events
                .slice(-8)
                .reverse()
                .map((event) => (
                  <button key={event.id} onClick={() => onEvidence(event)}>
                    <span>
                      <strong>{event.body.attributes.tool ?? event.event_type}</strong>
                      <small>{time(event.received_at)}</small>
                      <small>
                        {event.body.attributes.reason_code?.replaceAll("_", " ") ?? event.source}
                      </small>
                    </span>
                    <Status value={event.outcome} />
                    <ArrowRight size={13} />
                  </button>
                ))}
            </div>
          </>
        ) : (
          <>
            <div className="inspector-route-action">
              <span>Recorded route history</span>
              <button type="button" onClick={() => setFocused(true)}>
                <Maximize2 size={14} />
                Focus route lens
              </button>
            </div>
            <RouteLens
              session={session}
              events={events}
              inspectedVersion={inspectedVersion}
              onInspect={setInspectedVersion}
              onEvidence={onEvidence}
            />
          </>
        )}
      </div>
      <footer className="inspector-footer">
        <span>Case v{incident.version}</span>
        <Link className="button button-primary" to={`/incidents/${incident.id}`}>
          Open workbench
          <ArrowRight size={14} />
        </Link>
      </footer>
      <Modal
        open={focused}
        onOpenChange={setFocused}
        title={`Route lens / ${incident.number}`}
        description="Read-only historical inspection. It cannot replay a request or change access."
        wide
      >
        <RouteLens
          session={session}
          events={events}
          inspectedVersion={inspectedVersion}
          onInspect={setInspectedVersion}
          onEvidence={(event) => {
            setFocused(false);
            onEvidence(event);
          }}
        />
      </Modal>
    </aside>
  );
}

export function IncidentConsole({ onEvidence }: { onEvidence: (event: EventRecord) => void }) {
  const { origin, autoRefresh } = useWorkspace();
  const [status, setStatus] = useState("open");
  const [severity, setSeverity] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const result = useQuery({
    queryKey: ["operations-cases", status, severity, search, origin],
    queryFn: () =>
      api<Page<Incident>>(
        `/v1/incidents?${queryString({ limit: 12, status: status === "all" ? "" : status, severity, q: search, sort: "severity", origin })}`,
      ),
    refetchInterval: autoRefresh ? 20_000 : false,
    refetchOnWindowFocus: autoRefresh,
    refetchOnReconnect: autoRefresh,
  });
  const items = result.data?.items ?? [];
  const selectedId = items.some((item) => item.id === selected)
    ? (selected ?? undefined)
    : items[0]?.id;
  return (
    <section className="incident-console" aria-labelledby="triage-heading">
      <header className="console-section-heading">
        <div>
          <h2 id="triage-heading">Analyst queue</h2>
          <p>Prioritized cases. Evidence stays one selection away.</p>
        </div>
        <Link className="text-link" to="/incidents">
          Manage all incidents
          <ArrowRight size={14} />
        </Link>
      </header>
      <div className="console-workbench">
        <div className="queue-workspace">
          <div className="queue-tabs">
            <Tabs
              value={status}
              onChange={(value) => {
                setStatus(value);
                setSelected(null);
              }}
              tabs={[
                { value: "open", label: "Open" },
                { value: "investigating", label: "Investigating" },
                { value: "all", label: "All cases" },
              ]}
            />
            <span>{items.length} shown</span>
          </div>
          <div className="queue-filterbar">
            <div className="search-field">
              <Search size={15} />
              <input
                aria-label="Search analyst queue"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setSelected(null);
                }}
                placeholder="Search case, signal, or identity"
                maxLength={100}
              />
            </div>
            <select
              aria-label="Queue severity"
              value={severity}
              onChange={(event) => {
                setSeverity(event.target.value);
                setSelected(null);
              }}
            >
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
          {result.isPending ? (
            <Loading label="Reading the analyst queue..." />
          ) : result.isError ? (
            <ErrorState error={result.error} retry={() => void result.refetch()} />
          ) : items.length ? (
            <div className="case-table-scroll">
              <table className="case-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Case / signal</th>
                    <th>Identity</th>
                    <th>Response</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((incident, index) => (
                    <tr
                      key={incident.id}
                      className="queue-case-row"
                      data-selected={incident.id === selectedId}
                      onClick={() => setSelected(incident.id)}
                    >
                      <td data-label="Severity">
                        <Status value={incident.severity} />
                      </td>
                      <td className="queue-case-cell">
                        <button
                          className="queue-case"
                          aria-pressed={incident.id === selectedId}
                          onClick={() => setSelected(incident.id)}
                          onKeyDown={(event) => {
                            if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key))
                              return;
                            event.preventDefault();
                            const next =
                              event.key === "Home"
                                ? 0
                                : event.key === "End"
                                  ? items.length - 1
                                  : Math.max(
                                      0,
                                      Math.min(
                                        items.length - 1,
                                        index + (event.key === "ArrowDown" ? 1 : -1),
                                      ),
                                    );
                            setSelected(items[next].id);
                            const rows = event.currentTarget
                              .closest("table")
                              ?.querySelectorAll<HTMLButtonElement>(".queue-case");
                            rows?.[next]?.focus();
                          }}
                        >
                          <span>{incident.number}</span>
                          <strong>{incident.title}</strong>
                        </button>
                        <small>
                          {incident.rules.join(" + ")} ·{" "}
                          {incident.origin === "laboratory" ? "Lab execution" : "Direct API"}
                        </small>
                      </td>
                      <td data-label="Identity">
                        <span className="queue-identity">{incident.principal_id}</span>
                        <small>{incident.confidence} confidence</small>
                      </td>
                      <td data-label="Response">
                        <Status value={incident.route_mode ?? incident.status} />
                      </td>
                      <td data-label="Updated" className="queue-time">
                        {ago(incident.updated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="No cases match this view"
              description="Change the search or severity filter. An empty queue is not proof that all traffic is safe."
            />
          )}
          <footer className="queue-footer">
            <span>Tenant-scoped records. No model verdict grants access.</span>
            <a href="#selected-case" className="mobile-inspector-link">
              Inspect selected case
              <ArrowRight size={13} />
            </a>
            <Link className="text-link" to="/incidents">
              Full queue
              <ArrowRight size={13} />
            </Link>
          </footer>
        </div>
        <InvestigationPane
          key={selectedId ?? "empty"}
          identifier={selectedId}
          onEvidence={onEvidence}
        />
      </div>
    </section>
  );
}
