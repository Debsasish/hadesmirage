import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  CircleAlert,
  ClipboardCheck,
  Database,
  FlaskConical,
  Ghost,
  LockKeyhole,
  Pause,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  EvidenceDrawer,
  Loading,
  PageHeading,
  Panel,
  Status,
  ago,
} from "../components";
import { IncidentConsole } from "../components/incident-console";
import { RiskBoard } from "../components/risk-board";
import { useOverview, useWorkspace } from "../state";
import type { EventRecord, Overview, TrendBucket } from "../types";

function EventActivity({ data }: { data: TrendBucket[] }) {
  const [visible, setVisible] = useState(["authorized", "denied", "deception"]);
  const series = [
    { key: "authorized" as const, label: "Authorized", color: "var(--teal)" },
    { key: "denied" as const, label: "Denied", color: "var(--red)" },
    { key: "deception" as const, label: "Synthetic", color: "var(--purple)" },
  ];
  const totals = data.map((bucket) =>
    series.reduce((total, item) => total + (visible.includes(item.key) ? bucket[item.key] : 0), 0),
  );
  const maximum = Math.max(4, ...totals);
  return (
    <div className="event-activity">
      <div className="chart-legend">
        {series.map((item) => (
          <button
            key={item.key}
            aria-pressed={visible.includes(item.key)}
            className={!visible.includes(item.key) ? "dim" : ""}
            onClick={() =>
              setVisible((old) =>
                old.includes(item.key) ? old.filter((key) => key !== item.key) : [...old, item.key],
              )
            }
          >
            <i style={{ background: item.color }} />
            {item.label}
          </button>
        ))}
      </div>
      <svg
        viewBox="0 0 760 190"
        role="img"
        aria-label="Stored request outcomes, stacked by twelve server-receipt time buckets."
      >
        {[0, 1, 2, 3].map((index) => (
          <g key={index}>
            <line
              x1="36"
              x2="748"
              y1={18 + index * 45}
              y2={18 + index * 45}
              stroke="var(--border-soft)"
            />
            <text x="4" y={23 + index * 45} fill="var(--text-faint)" fontSize="13">
              {Math.round(maximum * (1 - index / 3))}
            </text>
          </g>
        ))}
        {data.map((bucket, index) => {
          let height = 0;
          return (
            <g key={index}>
              {series
                .filter((item) => visible.includes(item.key))
                .map((item) => {
                  const size = (bucket[item.key] / maximum) * 135;
                  const y = 153 - height - size;
                  height += size;
                  return size ? (
                    <rect
                      key={item.key}
                      x={45 + index * 58}
                      y={y}
                      width="28"
                      height={size}
                      rx="2"
                      fill={item.color}
                    >
                      <title>
                        {bucket.label}: {bucket[item.key]} {item.label.toLowerCase()}
                      </title>
                    </rect>
                  ) : null;
                })}
              <line
                x1={45 + index * 58}
                x2={73 + index * 58}
                y1="153"
                y2="153"
                stroke="var(--border)"
              />
              {(index % 3 === 0 || index === 11) && (
                <text
                  x={59 + index * 58}
                  y="180"
                  fill="var(--text-faint)"
                  fontSize="13"
                  textAnchor="middle"
                >
                  {bucket.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="chart-caption">
        <span>Receipt-time observations</span>
        <span>No estimated prevention score</span>
      </div>
    </div>
  );
}

function CaseDistribution({ data }: { data: Overview }) {
  const levels = [
    { name: "critical", color: "var(--red)" },
    { name: "high", color: "var(--red)" },
    { name: "medium", color: "var(--amber)" },
    { name: "low", color: "var(--blue)" },
  ];
  const total = Object.values(data.incident_severities).reduce((sum, count) => sum + count, 0);
  let start = 0;
  return (
    <Panel
      title="Open case severity"
      subtitle="Impact classification, not intent"
      className="case-distribution"
    >
      <div className="distribution-overview">
        <svg
          viewBox="0 0 130 130"
          role="img"
          aria-label={`${total} unresolved cases in the selected overview window`}
        >
          <circle
            cx="65"
            cy="65"
            r="50"
            fill="none"
            stroke="var(--surface-hover)"
            strokeWidth="12"
          />
          {levels.map((level) => {
            const amount =
              ((data.incident_severities[level.name] ?? 0) / Math.max(1, total)) * 314.159;
            const offset = start;
            start += amount;
            return amount > 0 ? (
              <circle
                key={level.name}
                cx="65"
                cy="65"
                r="50"
                fill="none"
                stroke={level.color}
                strokeWidth="12"
                strokeDasharray={`${amount} ${314.159 - amount}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 65 65)"
              />
            ) : null;
          })}
          <text x="65" y="64" textAnchor="middle" fill="var(--text)" fontSize="26" fontWeight="500">
            {total}
          </text>
          <text x="65" y="84" textAnchor="middle" fill="var(--text-faint)" fontSize="13">
            open cases
          </text>
        </svg>
        <div className="distribution-legend">
          {levels.map((level) => (
            <Link
              key={level.name}
              to={`/incidents?severity=${level.name}`}
              title={`View all ${level.name}-severity cases`}
            >
              <i style={{ background: level.color }} />
              <span>{level.name}</span>
              <strong>{data.incident_severities[level.name] ?? 0}</strong>
            </Link>
          ))}
        </div>
      </div>
      <Link className="distribution-action" to="/guardrails?tab=approvals">
        <ClipboardCheck size={16} />
        <span>Pending approvals</span>
        <strong>{data.pending_approvals}</strong>
        <ArrowRight size={14} />
      </Link>
    </Panel>
  );
}

export function OverviewPage() {
  const overview = useOverview();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { hours, autoRefresh, setAutoRefresh, setScenarioOpen } = useWorkspace();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("cases");
  const [event, setEvent] = useState<EventRecord | null>(null);
  const [eventFilter, setEventFilter] = useState("all");
  if (overview.isPending) return <Loading label="Loading the operations overview..." />;
  if (overview.isError)
    return <ErrorState error={overview.error} retry={() => void overview.refetch()} />;
  const data = overview.data;
  const isolation =
    data.isolation.verified && new Date(data.isolation.expires_at).getTime() > Date.now();
  const observations = data.recent_events.filter(
    (item) => eventFilter === "all" || item.outcome === eventFilter,
  );
  const refresh = () => {
    void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "me" });
  };
  return (
    <div className="page soc-overview">
      <PageHeading
        title="Risk overview"
        description="What attacked us, what we blocked, and what moved into the honeypot."
        actions={
          <>
            <button
              className="auto-refresh-control"
              aria-pressed={autoRefresh}
              onClick={() => setAutoRefresh(!autoRefresh)}
              title="Display refresh only. Enforcement and collection continue."
            >
              {autoRefresh ? <Pause size={14} /> : <Play size={14} />}
              {autoRefresh ? "Pause auto refresh" : "Resume auto refresh"}
            </button>
            <Button
              aria-label="Refresh workspace records"
              title="Refresh workspace records"
              busy={overview.isFetching}
              onClick={refresh}
            >
              <RefreshCw size={15} />
              Refresh
            </Button>
            <Button variant="primary" onClick={() => setScenarioOpen(true)}>
              <FlaskConical size={15} />
              Run lab scenario
            </Button>
          </>
        }
      />
      <RiskBoard />
      <form
        className="soc-record-search"
        onSubmit={(event) => {
          event.preventDefault();
          const q = query.trim();
          if (q)
            navigate(
              scope === "cases"
                ? `/incidents?q=${encodeURIComponent(q)}`
                : `/audit?tab=events&q=${encodeURIComponent(q)}`,
            );
        }}
      >
        <Search size={19} />
        <label className="sr-only" htmlFor="security-record-search">
          Search security records
        </label>
        <input
          id="security-record-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          maxLength={100}
          placeholder={
            scope === "cases"
              ? "Search cases by reference, signal or identity"
              : "Search stored events by ID or event type"
          }
        />
        <select
          aria-label="Security search scope"
          value={scope}
          onChange={(event) => setScope(event.target.value)}
        >
          <option value="cases">Cases</option>
          <option value="events">Events</option>
        </select>
        <Button type="submit" variant="primary" disabled={!query.trim()}>
          Search
          <ArrowRight size={15} />
        </Button>
      </form>
      <section className="soc-metrics" aria-label="Recorded operation totals">
        <Link className="summary-figure" to="/incidents">
          <span>Open incidents</span>
          <strong>{data.open_incidents.toLocaleString()}</strong>
          <small>{data.incident_severities.high ?? 0} high severity</small>
        </Link>
        <Link className="summary-figure" to="/audit?tab=events">
          <span>Recorded events</span>
          <strong>
            {data.event_count.toLocaleString()}
            {data.event_count_capped ? "+" : ""}
          </strong>
          <small>Last {hours} hours</small>
        </Link>
        <Link className="summary-figure figure-denied" to="/audit?tab=events&outcome=deny">
          <span>Denied operations</span>
          <strong>{data.denied_operations.toLocaleString()}</strong>
          <small>Before protected dispatch</small>
        </Link>
        <Link className="summary-figure" to="/agents">
          <span>Registered agents</span>
          <strong>{data.registered_agents.toLocaleString()}</strong>
          <small>{data.protected_applications} protected application</small>
        </Link>
        <Link className="summary-figure figure-synthetic" to="/deception">
          <span>Active deception</span>
          <strong>{data.active_decoys.toLocaleString()}</strong>
          <small>Synthetic sessions only</small>
        </Link>
      </section>
      <div className="soc-analytics">
        <Panel
          title="Event activity"
          subtitle={`Authorized, denied and synthetic outcomes / last ${hours} hours`}
          action={
            <Link className="text-link" to="/audit?tab=events">
              Explore events
              <ArrowUpRight size={14} />
            </Link>
          }
          className="event-activity-panel"
        >
          <EventActivity data={data.trend} />
        </Panel>
        <CaseDistribution data={data} />
      </div>
      <IncidentConsole onEvidence={setEvent} />
      <div className="soc-support-grid">
        <Panel
          title="Recent security events"
          subtitle="Latest stored observations. Select a record to inspect it."
          action={
            <div
              className="event-lane-controls"
              role="group"
              aria-label="Recent observation filter"
            >
              {[
                { value: "all", label: "All" },
                { value: "deny", label: "Denied" },
                { value: "simulated", label: "Synthetic" },
              ].map((filter) => (
                <button
                  key={filter.value}
                  aria-pressed={eventFilter === filter.value}
                  onClick={() => setEventFilter(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          }
        >
          {observations.length ? (
            <div className="recent-event-table">
              <table>
                <thead>
                  <tr>
                    <th>Event / tool</th>
                    <th>Principal</th>
                    <th>Outcome</th>
                    <th>Received</th>
                  </tr>
                </thead>
                <tbody>
                  {observations.slice(0, 6).map((item) => (
                    <tr key={item.id}>
                      <td>
                        <button className="event-record-link" onClick={() => setEvent(item)}>
                          <span className="record-event-icon">
                            {item.outcome === "simulated" ? (
                              <Ghost size={15} />
                            ) : item.outcome === "deny" ? (
                              <LockKeyhole size={15} />
                            ) : (
                              <Activity size={15} />
                            )}
                          </span>
                          <span>
                            <strong>{item.body.attributes.tool ?? item.event_type}</strong>
                            <small>
                              {item.body.attributes.reason_code?.replaceAll("_", " ") ??
                                "Recorded observation"}
                            </small>
                          </span>
                        </button>
                      </td>
                      <td data-label="Principal">{item.body.principal_id}</td>
                      <td data-label="Outcome">
                        <Status value={item.outcome} />
                      </td>
                      <td className="nowrap" data-label="Received">
                        {ago(item.received_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="No matching recent observations"
              description="This filter applies to the latest stored set, not the full retained history."
            />
          )}
          <div className="panel-footer">
            <span>All visitor and model text stays inert.</span>
            <Link className="text-link" to="/audit?tab=events">
              All stored events
              <ArrowRight size={14} />
            </Link>
          </div>
        </Panel>
        <Panel
          title="System readiness"
          subtitle="Actual control state, not a protection score"
          className="system-readiness"
        >
          <div className="readiness-list">
            <Link to="/guardrails">
              <ShieldCheck size={17} />
              <span>
                <strong>Application policy</strong>
                <small>{data.policy_version}</small>
              </span>
              <Badge tone="teal">Enforced</Badge>
            </Link>
            <Link to="/deception">
              <Ghost size={17} />
              <span>
                <strong>Synthetic runtime</strong>
                <small>Wasm capability boundary</small>
              </span>
              <Badge tone={isolation ? "purple" : "amber"}>
                {isolation ? "Verified" : "Unavailable"}
              </Badge>
            </Link>
            <Link to="/integrations">
              <Database size={17} />
              <span>
                <strong>Native gateway</strong>
                <small>Separate P3 network profile</small>
              </span>
              <Badge>Unconfigured</Badge>
            </Link>
            <Link to="/audit?tab=backend">
              {data.backend_ready ? <Check size={17} /> : <CircleAlert size={17} />}
              <span>
                <strong>Backend ledger</strong>
                <small>
                  {data.outbox_pending
                    ? `${data.outbox_pending} outbox records pending`
                    : "Durable outbox drained"}
                </small>
              </span>
              <Badge tone={data.backend_ready ? "teal" : "red"}>
                {data.backend_ready ? "Reachable" : "Unavailable"}
              </Badge>
            </Link>
          </div>
          <div className="model-budget-row">
            <Bot size={17} />
            <div>
              <strong>Advisory investigator</strong>
              <span>
                {data.model.provider === "fixture-investigator-v1"
                  ? "Deterministic fixture"
                  : data.model.provider}
              </span>
            </div>
            <span>
              {data.model.calls}/{data.model.budget} calls
            </span>
          </div>
          <p className="readiness-boundary">
            No model can grant access. Capability isolation is not a native gateway or TCP firewall
            measurement.
          </p>
        </Panel>
      </div>
      <div className="soc-footnote">
        <span>
          <span className="tiny-dot" />
          {overview.isFetching
            ? "Reading authoritative records"
            : `Last refreshed ${ago(new Date(overview.dataUpdatedAt).toISOString())}`}
        </span>
        <Link to="/settings">
          P1-native · synthetic data · scope and limitations
          <ArrowUpRight size={13} />
        </Link>
      </div>
      <EvidenceDrawer event={event} onClose={() => setEvent(null)} />
    </div>
  );
}
