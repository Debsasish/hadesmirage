import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Database,
  Download,
  FileCheck2,
  FileClock,
  Search,
  ShieldCheck,
} from "lucide-react";
import { api, download, queryString } from "../api";
import {
  Badge,
  Button,
  CodeBlock,
  Empty,
  ErrorState,
  EvidenceDrawer,
  KeyValue,
  Loading,
  Modal,
  PageHeading,
  Pagination,
  Panel,
  Status,
  Tabs,
  short,
  time,
} from "../components";
import { useAction, useFilters, useWorkspace } from "../state";
import type { AuditRecord, BackendEvidence, EventRecord, Incident, Page } from "../types";

function BackendLedger() {
  const result = useQuery({
    queryKey: ["backend-evidence"],
    queryFn: () => api<BackendEvidence>("/v1/backend/evidence"),
  });
  if (result.isPending) return <Loading label="Reading the independent backend ledger..." />;
  if (result.isError) return <ErrorState error={result.error} />;
  return (
    <Panel
      title="Independent synthetic backend evidence"
      subtitle="Effects are recorded by the separate backend, not inferred from authorization or model text."
      action={<Database size={18} className="teal" />}
    >
      <div className="ledger-summary">
        <div>
          <strong>{result.data.production_reads}</strong>
          <span>Actual synthetic reads</span>
        </div>
        <div>
          <strong>{result.data.production_mutations}</strong>
          <span>Actual synthetic mutations</span>
        </div>
        <div>
          <Badge tone="blue">Separate ledger</Badge>
          <span>No decoy results included</span>
        </div>
      </div>
      {result.data.effects.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Execution ID</th>
                <th>Tool</th>
                <th>Backend effect</th>
                <th>Recorded at</th>
              </tr>
            </thead>
            <tbody>
              {result.data.effects
                .slice(-50)
                .reverse()
                .map((effect) => (
                  <tr key={effect.execution_id}>
                    <td className="mono small">{effect.execution_id}</td>
                    <td className="mono small">{effect.tool}</td>
                    <td>
                      <Badge tone={effect.mutated ? "amber" : "teal"}>
                        {effect.mutated ? "Synthetic mutation" : "Read only"}
                      </Badge>
                    </td>
                    <td className="muted">{time(effect.created_at)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="No backend effects recorded" />
      )}
    </Panel>
  );
}

function Reports() {
  const result = useQuery({
    queryKey: ["report-cases"],
    queryFn: () => api<Page<Incident>>("/v1/incidents?limit=100"),
  });
  const [format, setFormat] = useState("json");
  const exportAction = useAction(
    (id: string) =>
      download(`/v1/incidents/${id}/export?format=${format}`, `mirage-case-${id}.${format}`),
    "Profile-labeled case export downloaded.",
  );
  if (result.isPending) return <Loading />;
  if (result.isError) return <ErrorState error={result.error} />;
  return (
    <>
      <div className="callout">
        <FileCheck2 size={19} />
        <div>
          Exports include observed evidence, rule conclusions, advisory analysis, source/config
          provenance, the validated profile and known gaps. They do not certify production
          readiness.
        </div>
      </div>
      <Panel
        title="Evidence-backed case reports"
        action={
          <select
            aria-label="Report format"
            value={format}
            onChange={(event) => setFormat(event.target.value)}
          >
            <option value="json">Structured JSON</option>
            <option value="html">Standalone HTML</option>
            <option value="md">Markdown</option>
          </select>
        }
      >
        {result.data.items.length ? (
          <div className="report-list">
            {result.data.items.map((item) => (
              <div key={item.id}>
                <span className="report-icon">
                  <FileCheck2 size={22} />
                </span>
                <div>
                  <Link className="text-link" to={`/incidents/${item.id}`}>
                    {item.number} / {item.title}
                    <ArrowUpRight size={13} />
                  </Link>
                  <p>
                    {item.rules.join(" + ")} / {time(item.updated_at)} / {item.origin}
                  </p>
                </div>
                <Status value={item.severity} />
                <Button busy={exportAction.isPending} onClick={() => exportAction.mutate(item.id)}>
                  <Download size={14} />
                  Export
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <Empty title="No case reports available yet" />
        )}
      </Panel>
    </>
  );
}

export function AuditPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "audit";
  const { origin } = useWorkspace();
  const [filters, setFilters] = useFilters(
    "audit",
    {
      q: "",
      outcome: "",
      source: "",
    },
    params.has("q") || params.has("outcome")
      ? {
          q: params.get("q") ?? "",
          outcome: params.get("outcome") ?? "",
          source: "",
        }
      : {},
  );
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [selectedAudit, setSelectedAudit] = useState<AuditRecord | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<EventRecord | null>(null);
  const audits = useQuery({
    queryKey: ["audit", filters.q, cursors.at(-1)],
    queryFn: () =>
      api<Page<AuditRecord>>(`/v1/audit?${queryString({ q: filters.q, cursor: cursors.at(-1) })}`),
    enabled: tab === "audit",
  });
  const events = useQuery({
    queryKey: ["events", filters, cursors.at(-1), origin],
    queryFn: () =>
      api<Page<EventRecord>>(
        `/v1/events?${queryString({ ...filters, cursor: cursors.at(-1), origin })}`,
      ),
    enabled: tab === "events",
  });
  const query = tab === "events" ? events : audits;
  function change(name: keyof typeof filters, value: string) {
    if (params.has("q") || params.has("outcome")) setParams({ tab }, { replace: true });
    setFilters({ ...filters, [name]: value });
    setCursors([null]);
  }
  return (
    <div className="page">
      <PageHeading
        eyebrow="EVIDENCE / AUDITABLE OUTCOMES"
        title="Reports"
        description="Reconstruct what happened, who authorized it, and what actually reached the backend."
        actions={<Badge tone="teal">Append-only application audit</Badge>}
      />
      <Tabs
        value={tab}
        onChange={(value) => {
          setParams({ tab: value });
          setCursors([null]);
        }}
        tabs={[
          {
            value: "audit",
            label: (
              <>
                <FileClock size={15} />
                Audit trail
              </>
            ),
          },
          {
            value: "events",
            label: (
              <>
                <Search size={15} />
                Security events
              </>
            ),
          },
          {
            value: "backend",
            label: (
              <>
                <Database size={15} />
                Backend ledger
              </>
            ),
          },
          {
            value: "reports",
            label: (
              <>
                <FileCheck2 size={15} />
                Case reports
              </>
            ),
          },
        ]}
      />
      {tab === "reports" ? (
        <Reports />
      ) : tab === "backend" ? (
        <BackendLedger />
      ) : (
        <Panel>
          <div className="filter-bar">
            <div className="search-field">
              <Search size={16} />
              <input
                aria-label={tab === "events" ? "Search events" : "Search audit trail"}
                value={filters.q}
                placeholder={
                  tab === "events" ? "Event ID or type..." : "Action, actor, or object ID..."
                }
                maxLength={100}
                onChange={(event) => change("q", event.target.value)}
              />
            </div>
            {tab === "events" && (
              <>
                <select
                  aria-label="Filter event outcome"
                  value={filters.outcome}
                  onChange={(event) => change("outcome", event.target.value)}
                >
                  <option value="">All outcomes</option>
                  {[
                    "allow",
                    "deny",
                    "require_approval",
                    "simulated",
                    "observed",
                    "success",
                    "failure",
                  ].map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
                <select
                  aria-label="Filter event producer"
                  value={filters.source}
                  onChange={(event) => change("source", event.target.value)}
                >
                  <option value="">All producers</option>
                  {["edge", "dispatcher", "control", "gateway", "decoy_router"].map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </>
            )}
          </div>
          {query.isPending ? (
            <Loading />
          ) : query.isError ? (
            <ErrorState error={query.error} />
          ) : tab === "events" ? (
            events.data?.items.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Observation</th>
                      <th>Producer</th>
                      <th>Outcome</th>
                      <th>Route / source</th>
                      <th>Received</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.data.items.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <button className="case-link" onClick={() => setSelectedEvent(item)}>
                            <strong>{item.body.attributes.tool ?? item.event_type}</strong>
                            <span className="mono small muted">{short(item.id)}</span>
                          </button>
                        </td>
                        <td>{item.source}</td>
                        <td>
                          <Status value={item.outcome} />
                        </td>
                        <td>
                          <Badge
                            dot={false}
                            tone={item.body.route_mode === "DECOY" ? "purple" : "neutral"}
                          >
                            {item.body.route_mode}
                          </Badge>
                          <span className="table-meta">{item.origin}</span>
                        </td>
                        <td className="muted nowrap">{time(item.received_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty title="No events match these filters" />
            )
          ) : audits.data?.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Sequence / action</th>
                    <th>Verified actor</th>
                    <th>Object</th>
                    <th>Receipt time</th>
                    <th>
                      <span className="sr-only">Details</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {audits.data.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.action}</strong>
                        <span className="table-meta mono">
                          #{item.sequence} / {item.integrity_digest.slice(0, 12)}...
                        </span>
                      </td>
                      <td className="mono small">{item.actor_id}</td>
                      <td className="mono small">{short(item.object_id)}</td>
                      <td className="muted nowrap">{time(item.created_at)}</td>
                      <td>
                        <Button variant="ghost" onClick={() => setSelectedAudit(item)}>
                          Inspect
                          <ArrowUpRight size={13} />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="No audit records match" />
          )}
          <Pagination
            pageNumber={cursors.length}
            loading={query.isFetching}
            previous={
              cursors.length > 1 ? () => setCursors((value) => value.slice(0, -1)) : undefined
            }
            next={
              query.data?.next_cursor
                ? () => setCursors((value) => [...value, query.data.next_cursor])
                : undefined
            }
          />
          <div className="panel-footnote">
            <ShieldCheck size={14} />
            Application hash chaining is not externally anchored tamper-proof storage.
          </div>
        </Panel>
      )}
      <Modal
        open={!!selectedAudit}
        onOpenChange={(open) => {
          if (!open) setSelectedAudit(null);
        }}
        title="Audited control action"
        description="Actor, exact object reference, and application hash-chain context."
        drawer
      >
        {selectedAudit && (
          <>
            <dl className="detail-list">
              <KeyValue label="Action">{selectedAudit.action}</KeyValue>
              <KeyValue label="Verified actor">{selectedAudit.actor_id}</KeyValue>
              <KeyValue label="Object ID" mono>
                {selectedAudit.object_id}
              </KeyValue>
              <KeyValue label="Receipt time">{time(selectedAudit.created_at)}</KeyValue>
              <KeyValue label="Sequence">{selectedAudit.sequence}</KeyValue>
            </dl>
            <CodeBlock label="Recorded details" value={selectedAudit.details} />
            <CodeBlock
              label="Integrity digest / local application chain"
              value={selectedAudit.integrity_digest}
            />
            <CodeBlock label="Previous digest" value={selectedAudit.previous_digest} />
          </>
        )}
      </Modal>
      <EvidenceDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
    </div>
  );
}
