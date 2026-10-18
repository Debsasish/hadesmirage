import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ChevronRight,
  CircleAlert,
  Download,
  FileText,
  Ghost,
  LockKeyhole,
  MessageSquare,
  Search,
  ShieldCheck,
  ShieldHalf,
  Sparkles,
} from "lucide-react";
import { api, download, post, queryString } from "../api";
import {
  Badge,
  Button,
  Confirm,
  Empty,
  ErrorState,
  EvidenceDrawer,
  IncidentTable,
  KeyValue,
  Loading,
  PageHeading,
  Pagination,
  Panel,
  Status,
  Tabs,
  ago,
  short,
  time,
} from "../components";
import { useAction, useFilters, useMe, useWorkspace } from "../state";
import type { CaseDetail, EventRecord, Incident, Page } from "../types";
import { CaseAssistant, useAIStatus } from "../components/ai-workflows";
import { IssueDrawer, IssuePanel } from "../components/issue-panel";
import { LensToggle } from "../experience";

export function IncidentsPage() {
  const { origin } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [filters, setFilters] = useFilters(
    "incidents",
    {
      q: "",
      severity: "",
      status: "",
      confidence: "",
      source: "",
      response: "",
      sort: "updated",
    },
    ["q", "severity", "status", "response"].some((key) => params.has(key))
      ? {
          q: params.get("q") ?? "",
          severity: params.get("severity") ?? "",
          status: params.get("status") ?? "",
          response: params.get("response") ?? "",
          confidence: "",
          source: "",
          sort: "updated",
        }
      : {},
  );
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors.at(-1);
  const result = useQuery({
    queryKey: ["incidents", filters, cursor, origin],
    queryFn: () =>
      api<Page<Incident>>(`/v1/incidents?${queryString({ ...filters, cursor, origin })}`),
  });
  function change(name: keyof typeof filters, value: string) {
    if (params.toString()) setParams({}, { replace: true });
    setFilters({ ...filters, [name]: value });
    setCursors([null]);
  }
  const issue = params.get("issue");
  const [previewEvent, setPreviewEvent] = useState<EventRecord | null>(null);
  return (
    <div className="page">
      <PageHeading
        eyebrow="INVESTIGATION / CASE QUEUE"
        title="Issues"
        description="Every suspicious behaviour we caught, explained in plain words or technical detail."
        actions={<LensToggle />}
      />
      <div className="incident-explainer">
        <ShieldHalf size={19} />
        <span>
          A rule match is a reason to investigate, not proof of malicious intent or successful
          compromise.
        </span>
      </div>
      <Panel>
        <div className="filter-bar">
          <div className="search-field">
            <Search size={16} />
            <input
              aria-label="Search incidents"
              placeholder="Search cases, signals, identities..."
              value={filters.q}
              onChange={(event) => change("q", event.target.value)}
              maxLength={100}
            />
          </div>
          <select
            aria-label="Filter severity"
            value={filters.severity}
            onChange={(event) => change("severity", event.target.value)}
          >
            <option value="">All severities</option>
            {["critical", "high", "medium", "low"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <select
            aria-label="Filter status"
            value={filters.status}
            onChange={(event) => change("status", event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="investigating">Investigating</option>
            <option value="resolved">Resolved</option>
          </select>
          <select
            aria-label="Sort incidents"
            value={filters.sort}
            onChange={(event) => change("sort", event.target.value)}
          >
            <option value="updated">Recently updated</option>
            <option value="severity">Highest severity</option>
            <option value="oldest">Oldest first</option>
          </select>
        </div>
        <div className="secondary-filters">
          <span>Refine by</span>
          <select
            aria-label="Filter confidence"
            value={filters.confidence}
            onChange={(event) => change("confidence", event.target.value)}
          >
            <option value="">Any confidence</option>
            <option value="high">High confidence</option>
            <option value="medium">Medium confidence</option>
            <option value="low">Low confidence</option>
          </select>
          <select
            aria-label="Filter source"
            value={filters.source}
            onChange={(event) => change("source", event.target.value)}
          >
            <option value="">Any source</option>
            {["edge", "dispatcher", "gateway", "control", "decoy_router"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <select
            aria-label="Filter response"
            value={filters.response}
            onChange={(event) => change("response", event.target.value)}
          >
            <option value="">Any response</option>
            {["PRODUCTION", "RESTRICTED", "DECOY_PENDING", "DECOY", "TERMINATED"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <span className="application-filter">Procurement Workspace</span>
          <button
            className="text-link"
            onClick={() => {
              setParams({}, { replace: true });
              setFilters({
                q: "",
                severity: "",
                status: "",
                confidence: "",
                source: "",
                response: "",
                sort: "updated",
              });
              setCursors([null]);
            }}
          >
            Clear filters
          </button>
        </div>
        {result.isPending ? (
          <Loading />
        ) : result.isError ? (
          <ErrorState error={result.error} retry={() => void result.refetch()} />
        ) : (
          <IncidentTable items={result.data.items} onPreview={(id) => setParams({ issue: id })} />
        )}
        <Pagination
          pageNumber={cursors.length}
          loading={result.isFetching}
          previous={
            cursors.length > 1 ? () => setCursors((value) => value.slice(0, -1)) : undefined
          }
          next={
            result.data?.next_cursor
              ? () => setCursors((value) => [...value, result.data.next_cursor])
              : undefined
          }
        />
      </Panel>
      <IssueDrawer
        caseId={issue}
        onClose={() => setParams({}, { replace: true })}
        onEvidence={setPreviewEvent}
      />
      <EvidenceDrawer event={previewEvent} onClose={() => setPreviewEvent(null)} />
    </div>
  );
}

export function IncidentPage() {
  const { id } = useParams();
  const me = useMe();
  const aiProvider = useAIStatus();
  const result = useQuery({
    queryKey: ["incident", id],
    queryFn: () => api<CaseDetail>(`/v1/incidents/${id}`),
    refetchInterval: 20_000,
  });
  const [selectedEvent, setSelectedEvent] = useState<EventRecord | null>(null);
  const [timelineFilter, setTimelineFilter] = useState("all");
  const [note, setNote] = useState("");
  const [terminateOpen, setTerminateOpen] = useState(false);
  const [responseAction, setResponseAction] = useState<"restrict" | "engage">("restrict");
  const [responseOpen, setResponseOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState("json");
  const inspectEvidence = useAction<EventRecord, string>(async (reference) => {
    const local = result.data?.events.find((item) => item.id === reference);
    if (local) return local;
    const sessionId = result.data?.session.id;
    if (!sessionId) throw new Error("Load the case before inspecting evidence.");
    const response = await api<Page<EventRecord>>(
      `/v1/events?${queryString({ q: reference, session_id: sessionId, limit: 1 })}`,
    );
    const event = response.items.find(
      (item) => item.id === reference && item.session_id === sessionId,
    );
    if (!event) throw new Error("The referenced case observation is unavailable.");
    return event;
  });
  const investigate = useAction(
    () => post(`/v1/incidents/${id}/investigate`),
    "Evidence-cited explanation generated.",
  );
  const saveNote = useAction(
    () => post(`/v1/incidents/${id}/notes`, { text: note }),
    "Analyst note recorded.",
  );
  const exportAction = useAction(
    () =>
      download(
        `/v1/incidents/${id}/export?format=${exportFormat}`,
        `mirage-case-${id}.${exportFormat}`,
      ),
    "Case exported with profile and limitations.",
  );
  const updateStatus = useAction(
    (status: string) =>
      api(`/v1/incidents/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status, expected_version: result.data?.incident.version }),
      }),
    "Case status updated.",
  );
  const terminate = useAction(
    () =>
      post(`/v1/sessions/${result.data?.session.id}/terminate`, {
        expected_route_version: result.data?.session.route_version,
        reason_code: "ANALYST_TERMINATION",
        evidence_event_ids: [],
      }),
    "Session terminated. Production access was not restored.",
  );
  const respond = useAction(
    () =>
      post(`/v1/sessions/${result.data?.session.id}/${responseAction}`, {
        expected_route_version: result.data?.session.route_version,
        reason_code: "ANALYST_REVIEW",
        evidence_event_ids: [],
      }),
    "Response state recorded. Review the route evidence.",
  );
  if (result.isPending) return <Loading label="Loading the incident and its evidence..." />;
  if (result.isError)
    return <ErrorState error={result.error} retry={() => void result.refetch()} />;
  const { incident, events, session, rules, notes, investigation } = result.data;
  const filtered = events.filter(
    (item) =>
      timelineFilter === "all" ||
      (timelineFilter === "decoy"
        ? item.body.route_mode === "DECOY"
        : timelineFilter === "control"
          ? item.source === "control"
          : item.body.route_mode === "PRODUCTION"),
  );
  const admin = me.data?.principal.roles.includes("security_admin");
  return (
    <div className="page case-page">
      <Link to="/incidents" className="back-link">
        <ArrowLeft size={14} />
        All issues
      </Link>
      <IssuePanel caseId={incident.id} embedded onEvidence={setSelectedEvent} />
      <h2 className="workbench-divider">Detailed workbench</h2>
      <PageHeading
        eyebrow={`${incident.number} / ${incident.origin === "laboratory" ? "RECORDED LAB EXECUTION" : "DIRECT APPLICATION EVIDENCE"}`}
        title={incident.title}
        description={`${incident.principal_id} / Procurement Workspace / Opened ${time(incident.created_at)}`}
        actions={
          <>
            <select
              aria-label="Export format"
              value={exportFormat}
              onChange={(event) => setExportFormat(event.target.value)}
            >
              <option value="json">JSON</option>
              <option value="html">HTML</option>
              <option value="md">Markdown</option>
            </select>
            <Button busy={exportAction.isPending} onClick={() => exportAction.mutate()}>
              <Download size={15} />
              Export case
            </Button>
            <Button
              variant="primary"
              busy={investigate.isPending}
              disabled={result.data.model_budget.remaining === 0 || !aiProvider.data?.can_generate}
              onClick={() => investigate.mutate()}
            >
              <Sparkles size={15} />
              {investigation ? "Re-investigate" : "Investigate evidence"}
            </Button>
          </>
        }
      />
      <div className="case-meta-strip">
        <Status value={incident.severity} />
        <Badge tone="neutral">{incident.confidence} rule confidence</Badge>
        <Status value={session.route_mode} />
        <span className="muted">Case version {incident.version}</span>
        <span className="grow" />
        <label className="row small">
          Analyst status
          <select
            aria-label="Case status"
            value={incident.status}
            disabled={updateStatus.isPending}
            onChange={(event) => updateStatus.mutate(event.target.value)}
          >
            <option value="open">Open</option>
            <option value="investigating">Investigating</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>
      </div>
      <div className="case-grid">
        <div className="case-main">
          <Panel
            title="What the evidence establishes"
            action={<Badge dot={false}>Rule conclusion</Badge>}
          >
            <div className="panel-body">
              <p className="summary-text">{incident.summary}</p>
              <div className="rule-chips">
                {rules.map((rule) => (
                  <div key={rule.id}>
                    <span className="mono">{rule.id}</span>
                    <div>
                      <strong>{rule.name}</strong>
                      <small>
                        {rule.threshold} / {rule.version}
                      </small>
                    </div>
                    <Status value={rule.severity} />
                  </div>
                ))}
              </div>
              <div className="outcome-callout">
                <ShieldCheck size={19} />
                <div>
                  <strong>
                    {result.data.backend_outcomes.length
                      ? "Recorded backend outcomes are attached"
                      : "No backend execution is linked to this case"}
                  </strong>
                  <p>
                    {result.data.backend_outcomes.length
                      ? result.data.backend_outcomes
                          .map((item) => `${short(item.id)}: ${item.state}`)
                          .join(" / ")
                      : "This is not a claim about traffic outside the instrumented application."}
                  </p>
                  <Link to="/audit">
                    Inspect independent backend evidence
                    <ArrowRight size={13} />
                  </Link>
                </div>
              </div>
            </div>
          </Panel>
          <Panel
            title="Evidence timeline"
            subtitle={`${events.length} observations / ordered by server receipt`}
            action={<Badge tone="teal">Observed events</Badge>}
          >
            <div className="timeline-tabs">
              <Tabs
                value={timelineFilter}
                onChange={setTimelineFilter}
                tabs={[
                  { value: "all", label: "All evidence" },
                  { value: "production", label: "Production" },
                  { value: "decoy", label: "Decoy" },
                  { value: "control", label: "Control" },
                ]}
              />
            </div>
            {filtered.length ? (
              <div className="timeline">
                {filtered.map((item) => (
                  <button
                    key={item.id}
                    className={`timeline-entry ${selectedEvent?.id === item.id ? "selected" : ""}`}
                    onClick={() => setSelectedEvent(item)}
                  >
                    <span
                      className={`timeline-marker ${item.body.route_mode === "DECOY" ? "purple" : item.outcome === "deny" ? "red" : "teal"}`}
                    >
                      {item.source === "decoy_router" ? (
                        <Ghost size={14} />
                      ) : item.outcome === "deny" ? (
                        <LockKeyhole size={14} />
                      ) : (
                        <Activity size={14} />
                      )}
                    </span>
                    <div className="timeline-content">
                      <div className="timeline-entry-top">
                        <strong>{item.body.attributes.tool ?? item.event_type}</strong>
                        <time>{new Date(item.received_at).toLocaleTimeString()}</time>
                      </div>
                      <p>
                        {item.body.attributes.reason_code?.replaceAll("_", " ") ??
                          "Authenticated observation"}
                      </p>
                      {item.body.attributes.snippet && (
                        <div className="untrusted-snippet">{item.body.attributes.snippet}</div>
                      )}
                      <div className="row wrap">
                        <Status value={item.outcome} />
                        <Badge
                          tone={item.body.route_mode === "DECOY" ? "purple" : "neutral"}
                          dot={false}
                        >
                          {item.body.route_mode}
                        </Badge>
                        <span className="mono tiny muted">{short(item.id)}</span>
                        <ChevronRight size={13} />
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <Empty title="No evidence in this lane" />
            )}
          </Panel>
          <CaseAssistant
            key={incident.id}
            detail={result.data}
            onEvidence={(reference) =>
              inspectEvidence.mutate(reference, { onSuccess: setSelectedEvent })
            }
          />
          <Panel
            title="Analyst notes"
            subtitle="Human conclusions stay distinct from model inference."
            action={<MessageSquare size={17} />}
          >
            <div className="notes-list">
              {notes.map((item) => (
                <article className="analyst-note" key={item.id}>
                  <div>
                    <span className="avatar tiny">{item.actor_id[0].toUpperCase()}</span>
                    <strong>{item.actor_id}</strong>
                    <time>{ago(item.created_at)}</time>
                    <Badge dot={false}>Analyst conclusion</Badge>
                  </div>
                  <p>{item.text}</p>
                </article>
              ))}
            </div>
            <form
              className="note-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (note.trim()) saveNote.mutate(undefined, { onSuccess: () => setNote("") });
              }}
            >
              <label className="sr-only" htmlFor="case-note">
                Analyst note
              </label>
              <textarea
                id="case-note"
                rows={3}
                maxLength={2000}
                placeholder="Record a conclusion, alternative explanation, or follow-up..."
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <div>
                <small className="muted">{note.length} / 2000</small>
                <Button type="submit" busy={saveNote.isPending} disabled={!note.trim()}>
                  <FileText size={14} />
                  Add note
                </Button>
              </div>
            </form>
          </Panel>
        </div>
        <aside className="case-aside">
          <Panel title="Response state" action={<Ghost size={17} className="purple" />}>
            <div className="panel-body">
              <Status value={session.route_mode} />
              <dl className="detail-list">
                <KeyValue label="Session" mono>
                  {session.id}
                </KeyValue>
                <KeyValue label="Caller class">{session.caller_class}</KeyValue>
                <KeyValue label="Route version">{session.route_version}</KeyValue>
                <KeyValue label="Decoy" mono>
                  {session.decoy_id ?? "Not assigned"}
                </KeyValue>
                <KeyValue label="Expires">{time(session.expires_at)}</KeyValue>
              </dl>
              <div className="route-history">
                {session.history.map((item) => (
                  <div key={item.version}>
                    <i />
                    <span>
                      <strong>{item.mode}</strong>
                      <small>
                        v{item.version} / {item.reason.replaceAll("_", " ")}
                      </small>
                    </span>
                    <time>
                      {new Date(item.at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </time>
                  </div>
                ))}
              </div>
              {session.route_mode === "PRODUCTION" && (
                <Button
                  className="full-width"
                  onClick={() => {
                    setResponseAction("restrict");
                    setResponseOpen(true);
                  }}
                >
                  <LockKeyhole size={14} />
                  Restrict session
                </Button>
              )}
              {session.route_mode === "RESTRICTED" &&
                admin &&
                session.caller_class === "external" && (
                  <Button
                    className="full-width"
                    onClick={() => {
                      setResponseAction("engage");
                      setResponseOpen(true);
                    }}
                  >
                    <Ghost size={14} />
                    Check engagement eligibility
                  </Button>
                )}
              {session.route_mode !== "TERMINATED" && (
                <Button
                  variant="danger"
                  className="full-width"
                  onClick={() => setTerminateOpen(true)}
                >
                  Terminate session
                </Button>
              )}
              <p className="helper">No response action automatically restores production access.</p>
            </div>
          </Panel>
          <Panel title="Advisory investigation" action={<Sparkles size={17} className="purple" />}>
            <div className="panel-body">
              {incident.model_error && (
                <div className="callout callout-amber">
                  <CircleAlert size={16} />
                  <div>
                    Explanation unavailable: {incident.model_error}. Deterministic evidence is
                    unchanged.
                  </div>
                </div>
              )}
              {investigation ? (
                <>
                  <Badge tone="purple">
                    {investigation.provider === "fixture-investigator-v1"
                      ? "Deterministic fixture output"
                      : investigation.provider}
                  </Badge>
                  {investigation.case_version !== incident.version && (
                    <Badge tone="amber">
                      Earlier case snapshot / v{investigation.case_version}
                    </Badge>
                  )}
                  <p className="model-summary">{investigation.summary}</p>
                  <h3 className="mini-heading">MODEL INFERENCES / CITED EVIDENCE</h3>
                  {investigation.claims.map((claim, index) => (
                    <div className="model-claim" key={index}>
                      <p>{claim.text}</p>
                      <div className="evidence-refs">
                        {claim.evidence_event_ids.map((ref) => (
                          <button
                            key={ref}
                            onClick={() =>
                              inspectEvidence.mutate(ref, { onSuccess: setSelectedEvent })
                            }
                            title={ref}
                          >
                            {short(ref)}
                            <ArrowRight size={11} />
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                  <h3 className="mini-heading">ALTERNATIVES & EVIDENCE GAPS</h3>
                  <ul className="plain-list">
                    {investigation.alternative_explanations.map((text) => (
                      <li key={text}>{text}</li>
                    ))}
                  </ul>
                  <div className="model-recommendation">
                    <span>Suggested response</span>
                    <strong>{investigation.recommended_response.replaceAll("_", " ")}</strong>
                    <small>Advisory only. Does not change route or grants.</small>
                  </div>
                </>
              ) : (
                <div className="model-empty">
                  <Sparkles size={24} />
                  <h3>Evidence first. Explanation second.</h3>
                  <p>
                    Generate a bounded, case-cited explanation. Rules and enforcement work without a
                    model.
                  </p>
                  <small>
                    {incident.model_calls} / {result.data.model_budget.limit} shared case requests
                    used
                  </small>
                </div>
              )}
            </div>
          </Panel>
        </aside>
      </div>
      <EvidenceDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      <Confirm
        open={terminateOpen}
        onOpenChange={setTerminateOpen}
        title="Terminate this session?"
        description="Stops supported production and deception dispatch for this session."
        consequence="The session is permanently terminated. Any synthetic state is purged. Production access will not be restored, and already committed backend work is not undone."
        busy={terminate.isPending}
        label="Terminate session"
        onConfirm={() => terminate.mutate(undefined, { onSuccess: () => setTerminateOpen(false) })}
      />
      <Confirm
        open={responseOpen}
        onOpenChange={setResponseOpen}
        title={
          responseAction === "restrict"
            ? "Restrict production dispatch?"
            : "Evaluate isolated engagement?"
        }
        description="The controller rechecks the authoritative route version and deterministic eligibility."
        consequence={
          responseAction === "restrict"
            ? "New production dispatch is blocked at the shared fence. Already committed work remains recorded."
            : "Only a corroborated external session and ready verified template can be pinned. Failure leaves production restricted."
        }
        busy={respond.isPending}
        label={responseAction === "restrict" ? "Restrict session" : "Check and engage"}
        danger={false}
        onConfirm={() => respond.mutate(undefined, { onSuccess: () => setResponseOpen(false) })}
      />
    </div>
  );
}
