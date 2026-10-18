import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Clock3,
  Ghost,
  Layers3,
  Network,
  OctagonX,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api, post } from "../api";
import {
  Badge,
  Button,
  CodeBlock,
  Confirm,
  Empty,
  ErrorState,
  EvidenceDrawer,
  KeyValue,
  Loading,
  Meter,
  Modal,
  PageHeading,
  Panel,
  Status,
  Tabs,
  ago,
  short,
  time,
} from "../components";
import { useAction, useMe } from "../state";
import type { Attestation, Decoy, DeceptionData, EventRecord, Page } from "../types";

function remaining(expires: string) {
  const seconds = Math.max(0, (new Date(expires).getTime() - Date.now()) / 1000);
  return seconds > 0 ? `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s` : "Expired";
}

export function DeceptionPage() {
  const me = useMe();
  const [filter, setFilter] = useState("all");
  const [proof, setProof] = useState<Attestation | null>(null);
  const [selected, setSelected] = useState<Decoy | null>(null);
  const [terminate, setTerminate] = useState<Decoy | null>(null);
  const [killOpen, setKillOpen] = useState(false);
  const [event, setEvent] = useState<EventRecord | null>(null);
  const result = useQuery({
    queryKey: ["deception"],
    queryFn: () => api<DeceptionData>("/v1/deception"),
    refetchInterval: 15_000,
  });
  const events = useQuery({
    queryKey: ["decoy-events", selected?.session_id],
    queryFn: () =>
      api<Page<EventRecord>>(`/v1/events?session_id=${selected?.session_id}&limit=100`),
    enabled: !!selected,
  });
  const toggle = useAction(
    (enabled: boolean) =>
      api("/v1/settings", {
        method: "PATCH",
        body: JSON.stringify({ engagements_enabled: enabled }),
      }),
    "New-engagement policy updated. Authorization remains active.",
  );
  const verify = useAction<Attestation, void>(
    () => post("/v1/deception/verify"),
    "Runtime capability probes completed.",
  );
  const stopAll = useAction(
    () => post("/v1/deception/kill-switch", { confirmation: "TERMINATE ALL DECOY SESSIONS" }),
    "All active tenant engagements stopped. Production was not restored.",
  );
  const stopOne = useAction(async () => {
    const session = await api<{ route_version: number }>(`/v1/sessions/${terminate?.session_id}`);
    return post(`/v1/sessions/${terminate?.session_id}/terminate`, {
      expected_route_version: session.route_version,
      reason_code: "ANALYST_DECOY_TERMINATION",
      evidence_event_ids: [],
    });
  }, "Engagement terminated and synthetic state purged.");
  if (result.isPending)
    return <Loading label="Loading verified templates and engagement state..." />;
  if (result.isError)
    return <ErrorState error={result.error} retry={() => void result.refetch()} />;
  const data = result.data;
  const admin = me.data?.principal.roles.includes("security_admin");
  const items = data.items.filter(
    (item) =>
      filter === "all" || (filter === "active" ? item.state === "ACTIVE" : item.state !== "ACTIVE"),
  );
  return (
    <div className="page">
      <PageHeading
        eyebrow="DECEPTION / SYNTHETIC BY DESIGN"
        title="Honeypot"
        description="Engage only after production is restricted and the runtime boundary is verified."
        actions={
          <>
            <Button
              onClick={() => toggle.mutate(!data.engagements_enabled)}
              disabled={!admin}
              busy={toggle.isPending}
            >
              {data.engagements_enabled ? "Disable new engagements" : "Enable eligible engagements"}
            </Button>
            <Button variant="danger" onClick={() => setKillOpen(true)}>
              <OctagonX size={15} />
              Kill switch
            </Button>
          </>
        }
      />
      <div className="deception-banner">
        <Ghost size={23} />
        <div>
          <strong>
            {data.engagements_enabled
              ? "Eligible new engagements enabled"
              : "New engagements disabled"}
          </strong>
          <p>
            Decoys never receive production credentials or records. Stopping engagement never
            restores production access.
          </p>
        </div>
        <Badge tone="purple">Low-interaction / bounded</Badge>
      </div>
      <div className="template-grid">
        {data.templates.map((template) => (
          <Panel key={template.id}>
            <div className="template-card">
              <div className="row">
                <span className="icon-tile purple">
                  <Layers3 size={24} />
                </span>
                <div className="grow" />
                <Badge tone={template.ready ? "purple" : "amber"}>
                  {template.ready ? "Ready / capability-verified" : "Unavailable / fail closed"}
                </Badge>
              </div>
              <h2>{template.name}</h2>
              <p>{template.description}</p>
              <div className="template-tags">
                {template.tools.map((tool) => (
                  <code key={tool}>{tool}</code>
                ))}
              </div>
              <dl className="compact-details">
                <KeyValue label="Template version" mono>
                  {template.version}
                </KeyValue>
                <KeyValue label="Runtime">{template.runtime}</KeyValue>
                <KeyValue label="Last verification">{ago(template.isolation.verified_at)}</KeyValue>
                <KeyValue label="Memory / fuel">64 KiB / 100,000 units per request</KeyValue>
              </dl>
              <div className="template-actions">
                <Button onClick={() => setProof(template.isolation)}>
                  <ShieldCheck size={14} />
                  Inspect isolation evidence
                </Button>
                <Button
                  variant="ghost"
                  busy={verify.isPending}
                  disabled={!admin}
                  onClick={() => verify.mutate(undefined, { onSuccess: setProof })}
                >
                  <RefreshCw size={14} />
                  Reverify
                </Button>
              </div>
            </div>
          </Panel>
        ))}
        <Panel title="Engagement budgets" subtitle="Limits are enforced, not suggested.">
          <div className="panel-body">
            <Meter
              label="Concurrent active sessions"
              value={data.items.filter((item) => item.state === "ACTIVE").length}
              max={data.budgets.concurrent}
              tone="purple"
            />
            <dl className="detail-list">
              <KeyValue label="Session TTL">{data.budgets.ttl_seconds / 60} minutes</KeyValue>
              <KeyValue label="Request limit">{data.budgets.requests} / engagement</KeyValue>
              <KeyValue label="AI wording">
                {data.budgets.model_wording_enabled ? "Enabled with static fallback" : "Disabled"}
              </KeyValue>
              <KeyValue label="Wording admission budget">
                {data.budgets.wording_budget_units_per_session.toLocaleString()} units / engagement
              </KeyValue>
              <KeyValue label="Cleanup">Synthetic state purged on termination</KeyValue>
            </dl>
            <p className="helper">
              {data.budgets.wording_budget_definition}. Actual reported model tokens are tracked
              separately.
            </p>
            <div className="callout">
              <Network size={17} />
              <div>
                These probes prove absent Wasm host capabilities, not OS firewall reachability or
                native gateway enforcement.
              </div>
            </div>
          </div>
        </Panel>
      </div>
      <Panel
        title="Engagements"
        subtitle="Tenant/session-specific synthetic state and a monotonic route."
        action={
          <Tabs
            value={filter}
            onChange={setFilter}
            tabs={[
              { value: "all", label: "All" },
              { value: "active", label: "Active" },
              { value: "terminated", label: "Terminated" },
            ]}
          />
        }
      >
        {!items.length ? (
          <Empty
            title="No engagements in this view"
            description="A corroborated eligible external sequence can reserve a verified template. Missing readiness never falls back to production."
          />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Session / template</th>
                  <th>Lifecycle</th>
                  <th>Request budget</th>
                  <th>TTL remaining</th>
                  <th>Cleanup</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((decoy) => (
                  <tr key={decoy.id}>
                    <td>
                      <button className="text-link mono" onClick={() => setSelected(decoy)}>
                        {short(decoy.session_id)}
                        <ArrowUpRight size={12} />
                      </button>
                      <span className="table-meta">
                        {decoy.template_id} / {decoy.template_version}
                      </span>
                    </td>
                    <td>
                      <Status value={decoy.state} />
                      <span className="table-meta">
                        Evidence: {ago(decoy.attestation.verified_at)}
                      </span>
                    </td>
                    <td>
                      <Meter
                        value={decoy.requests}
                        max={data.budgets.requests}
                        label="Observed requests"
                        tone="purple"
                      />
                    </td>
                    <td>
                      <span className="row small">
                        <Clock3 size={13} />
                        {decoy.state === "ACTIVE" ? remaining(decoy.expires_at) : "Stopped"}
                      </span>
                    </td>
                    <td>
                      <Badge tone={decoy.cleanup_state === "purged" ? "teal" : "neutral"}>
                        {decoy.cleanup_state.replaceAll("_", " ")}
                      </Badge>
                    </td>
                    <td>
                      {decoy.state === "ACTIVE" && (
                        <Button variant="ghost" onClick={() => setTerminate(decoy)}>
                          Terminate
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Modal
        open={!!proof}
        onOpenChange={(open) => {
          if (!open) setProof(null);
        }}
        title="Runtime capability evidence"
        description="Executed against the actual Wasmtime linker with no host capabilities registered."
        wide
      >
        {proof && (
          <>
            <div className="row wrap">
              <Badge tone={proof.verified ? "purple" : "red"}>
                {proof.verified ? "Capability probes passed" : "Verification failed"}
              </Badge>
              <span className="muted small">{time(proof.verified_at)}</span>
            </div>
            <p className="helper">{proof.scope}</p>
            <div className="probe-grid">
              {proof.probes.map((probe) => (
                <div className="probe-row" key={probe.target}>
                  <span className="probe-icon">
                    {probe.denied ? <Check size={16} /> : <CircleAlert size={16} />}
                  </span>
                  <div>
                    <strong>{probe.target}</strong>
                    <p>{probe.evidence}</p>
                  </div>
                  <Badge tone={probe.denied ? "teal" : "red"}>
                    {probe.denied ? "Capability absent" : "Unexpected access"}
                  </Badge>
                </div>
              ))}
            </div>
            <CodeBlock label="Active compiled template SHA-256" value={proof.module_sha256} />
            <dl className="compact-details">
              <KeyValue label="Host imports">{proof.host_imports}</KeyValue>
              <KeyValue label="Verification expires">{time(proof.expires_at)}</KeyValue>
            </dl>
          </>
        )}
      </Modal>
      <Modal
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title="Synthetic engagement"
        description="Simulation results are not production side effects."
        drawer
      >
        {selected && (
          <>
            <dl className="detail-list">
              <KeyValue label="Decoy ID" mono>
                {selected.id}
              </KeyValue>
              <KeyValue label="Session ID" mono>
                {selected.session_id}
              </KeyValue>
              <KeyValue label="Template" mono>
                {selected.template_version}
              </KeyValue>
              <KeyValue label="Lifecycle">
                <Status value={selected.state} />
              </KeyValue>
              <KeyValue label="Requests">
                {selected.requests} / {data.budgets.requests}
              </KeyValue>
              <KeyValue label="Cleanup">{selected.cleanup_state}</KeyValue>
            </dl>
            <CodeBlock
              label="Bounded synthetic state / no production records"
              value={selected.synthetic_state}
            />
            <h3 className="mini-heading">BEHAVIOUR TIMELINE</h3>
            {events.isPending ? (
              <Loading />
            ) : events.isError ? (
              <ErrorState error={events.error} />
            ) : (
              events.data.items.map((item) => (
                <button className="mini-event" key={item.id} onClick={() => setEvent(item)}>
                  <span>
                    {item.body.attributes.tool ?? item.event_type}
                    <small>{time(item.received_at)}</small>
                  </span>
                  <Status value={item.outcome} />
                </button>
              ))
            )}
            <Link className="text-link" to="/incidents" onClick={() => setSelected(null)}>
              Open the incident queue
              <ArrowUpRight size={13} />
            </Link>
          </>
        )}
      </Modal>
      <EvidenceDrawer event={event} onClose={() => setEvent(null)} />
      <Confirm
        open={killOpen}
        onOpenChange={setKillOpen}
        title="Stop every active tenant engagement?"
        description="Emergency deception kill switch. Application authorization stays active."
        consequence="All active and pending decoy sessions in this tenant terminate. Synthetic state is purged and new engagement is disabled. No session returns to production. Already committed backend effects are not reversed."
        label="Terminate all decoy sessions"
        busy={stopAll.isPending}
        onConfirm={() => stopAll.mutate(undefined, { onSuccess: () => setKillOpen(false) })}
      />
      <Confirm
        open={!!terminate}
        onOpenChange={(open) => {
          if (!open) setTerminate(null);
        }}
        title="Terminate this engagement?"
        description={terminate?.session_id ?? ""}
        consequence="Future supported requests are denied. Synthetic state is purged; the session is never returned to production."
        label="Terminate engagement"
        busy={stopOne.isPending}
        onConfirm={() => stopOne.mutate(undefined, { onSuccess: () => setTerminate(null) })}
      />
    </div>
  );
}
