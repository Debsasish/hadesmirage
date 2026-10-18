import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Bot,
  CircleAlert,
  GitBranch,
  Layers3,
  LockKeyhole,
  Play,
  ShieldCheck,
  SlidersHorizontal,
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
  Field,
  KeyValue,
  Loading,
  Modal,
  PageHeading,
  Panel,
  Status,
  ago,
  time,
} from "../components";
import { useAction, useMe } from "../state";
import type { EventRecord, Incident, Invocation, Principal, Tool } from "../types";

const tools: { tool: Tool; action: Invocation["action"]; label: string }[] = [
  { tool: "supplier.lookup", action: "read", label: "Supplier lookup" },
  { tool: "invoice.compare", action: "analyze", label: "Invoice comparison" },
  { tool: "payment.change_request", action: "propose_change", label: "Payment change" },
  { tool: "customer.export", action: "export", label: "Customer export" },
  { tool: "infrastructure.delete", action: "delete", label: "Infrastructure deletion" },
];

function Simulator({ agents }: { agents: Principal[] }) {
  const [principalId, setPrincipalId] = useState(agents[0]?.id ?? "agent-procurement");
  const [tool, setTool] = useState<Tool>("supplier.lookup");
  const [resource, setResource] = useState("supplier:demo-001");
  const [account, setAccount] = useState("synthetic-account-proposed");
  const simulate = useAction<
    {
      simulation: boolean;
      executed: boolean;
      decision: string;
      reason_code: string;
      policy_version: string;
    },
    void
  >(() => {
    const selected = tools.find((item) => item.tool === tool);
    const identifier = resource.split(":")[1] ?? "";
    const invocation: Invocation = {
      tool,
      action: selected?.action ?? "read",
      resource,
      session_id: crypto.randomUUID(),
      arguments:
        tool === "invoice.compare"
          ? { invoice_id: identifier }
          : tool === "supplier.lookup"
            ? { supplier_id: identifier }
            : tool === "payment.change_request"
              ? { supplier_id: identifier, proposed_account_ref: account }
              : {},
    };
    return post("/v1/policies/simulate", { principal_id: principalId, invocation });
  });
  return (
    <Panel
      title="Policy simulator"
      subtitle="Evaluate a proposed operation without executing it."
      action={<Badge tone="blue">Simulation only</Badge>}
    >
      <form
        className="panel-body"
        onSubmit={(event) => {
          event.preventDefault();
          simulate.mutate();
        }}
      >
        <div className="form-grid">
          <Field label="Acting agent">
            <select value={principalId} onChange={(event) => setPrincipalId(event.target.value)}>
              {agents.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Tool and action">
            <select
              value={tool}
              onChange={(event) => {
                const selected = tools.find((item) => item.tool === event.target.value);
                if (!selected) return;
                setTool(selected.tool);
                setResource(
                  selected.tool === "invoice.compare"
                    ? "invoice:demo-001"
                    : selected.tool === "customer.export"
                      ? "customer:all"
                      : selected.tool === "infrastructure.delete"
                        ? "infrastructure:cluster"
                        : "supplier:demo-001",
                );
                simulate.reset();
              }}
            >
              {tools.map((item) => (
                <option value={item.tool} key={item.tool}>
                  {item.tool} / {item.action}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Exact resource">
            <input
              className="mono"
              value={resource}
              onChange={(event) => setResource(event.target.value)}
              required
              maxLength={200}
            />
          </Field>
          {tool === "payment.change_request" && (
            <Field label="Synthetic account reference">
              <input
                className="mono"
                value={account}
                onChange={(event) => setAccount(event.target.value)}
                required
              />
            </Field>
          )}
        </div>
        <div className="simulator-actions">
          <span>
            <LockKeyhole size={14} />
            No backend dispatch. No approval consumed.
          </span>
          <Button type="submit" variant="primary" busy={simulate.isPending}>
            <Play size={14} />
            Evaluate policy
          </Button>
        </div>
        {simulate.data && (
          <div className={`simulation-result simulation-${simulate.data.decision}`}>
            <div className="row">
              <Badge tone="blue">SIMULATION</Badge>
              <Status value={simulate.data.decision} />
            </div>
            <strong>{simulate.data.reason_code.replaceAll("_", " ")}</strong>
            <p className="mono small">
              {simulate.data.policy_version} / executed: {String(simulate.data.executed)}
            </p>
          </div>
        )}
        {simulate.isError && (
          <p className="error-text" role="alert">
            {simulate.error.message}
          </p>
        )}
      </form>
    </Panel>
  );
}

export function AgentsPage() {
  const [params] = useSearchParams();
  const me = useMe();
  const [selectedId, setSelectedId] = useState<string | null>(params.get("agent"));
  const [confirmStatus, setConfirmStatus] = useState<Principal | null>(null);
  const [event, setEvent] = useState<EventRecord | null>(null);
  const result = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<{ items: Principal[] }>("/v1/agents"),
  });
  const detail = useQuery({
    queryKey: ["agent", selectedId],
    queryFn: () =>
      api<{
        principal: Principal;
        decisions: EventRecord[];
        incidents: Incident[];
        destination_state: string;
      }>(`/v1/agents/${selectedId}`),
    enabled: !!selectedId,
  });
  const status = useAction(
    () =>
      post(`/v1/agents/${confirmStatus?.id}/status`, {
        status: confirmStatus?.status === "active" ? "suspended" : "active",
      }),
    "Identity status updated. Terminated sessions stay terminated.",
  );
  if (result.isPending) return <Loading label="Loading verified agent identities..." />;
  if (result.isError)
    return <ErrorState error={result.error} retry={() => void result.refetch()} />;
  const agents = result.data.items;
  const admin = me.data?.principal.roles.includes("security_admin");
  return (
    <div className="page">
      <PageHeading
        eyebrow="IDENTITY / BOUNDED WORKLOAD AUTHORITY"
        title="AI agents"
        description="Every agent has an identity, an owner, and an explicit boundary."
        actions={
          <Link className="button button-secondary" to="/guardrails">
            <SlidersHorizontal size={15} />
            Manage policy
          </Link>
        }
      />
      <div className="application-card">
        <span className="icon-tile teal">
          <Layers3 size={23} />
        </span>
        <div>
          <span className="object-context">Protected application</span>
          <h2>Procurement Workspace</h2>
          <p>
            Synthetic suppliers, invoice comparison, and approval-bound payment-change requests.
          </p>
        </div>
        <Badge tone="teal">Instrumented L7</Badge>
        <Badge tone="neutral">HTTP / JSON</Badge>
      </div>
      <div className="agent-grid">
        {agents.map((agent) => (
          <article className="panel agent-card" key={agent.id}>
            <header>
              <span className="agent-avatar">
                <Bot size={24} />
              </span>
              <Status value={agent.status} />
              <button
                className="icon-button"
                aria-label={`Open ${agent.name}`}
                onClick={() => setSelectedId(agent.id)}
              >
                <ArrowUpRight size={17} />
              </button>
            </header>
            <h2>
              <button onClick={() => setSelectedId(agent.id)}>{agent.name}</button>
            </h2>
            <p className="mono small muted">{agent.id}</p>
            <dl className="compact-details">
              <KeyValue label="Owner">{agent.owner}</KeyValue>
              <KeyValue label="Application">Procurement Workspace</KeyValue>
              <KeyValue label="Grant expiry">{time(agent.expires_at)}</KeyValue>
              <KeyValue label="Lineage">
                <span className="row">
                  <GitBranch size={13} />
                  {agent.parent_id ?? "Root workload"} / depth {agent.depth}
                </span>
              </KeyValue>
            </dl>
            <div className="agent-scopes">
              {agent.scopes.map((scope) => (
                <span key={scope.tool}>
                  <ShieldCheck size={12} />
                  {scope.tool}
                </span>
              ))}
            </div>
            <footer>
              <span>
                {agent.scopes.reduce((count, scope) => count + scope.resources.length, 0)} explicit
                resource grants
              </span>
              <Button variant="ghost" onClick={() => setSelectedId(agent.id)}>
                Inspect identity
                <ArrowUpRight size={13} />
              </Button>
            </footer>
          </article>
        ))}
      </div>
      <Panel
        title="Configured permissions matrix"
        subtitle="Grants do not override live identity, route, policy or approval checks. Destination grants are separate."
        action={<Badge dot={false}>Deny by default</Badge>}
      >
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Tool / action</th>
                {agents.map((agent) => (
                  <th key={agent.id}>{agent.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tools.map((tool) => (
                <tr key={tool.tool}>
                  <td>
                    <strong className="mono small">{tool.tool}</strong>
                    <span className="table-meta">{tool.action}</span>
                  </td>
                  {agents.map((agent) => {
                    const scope = agent.scopes.find(
                      (item) => item.tool === tool.tool && item.action === tool.action,
                    );
                    return (
                      <td key={agent.id}>
                        <Badge
                          tone={
                            scope
                              ? tool.tool === "payment.change_request"
                                ? "amber"
                                : "teal"
                              : "neutral"
                          }
                        >
                          {scope
                            ? tool.tool === "payment.change_request"
                              ? "Exact approval"
                              : "Scoped grant"
                            : "No grant / deny"}
                        </Badge>
                        {scope && (
                          <span className="table-meta mono">{scope.resources.join(", ")}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel-footnote">
          <CircleAlert size={14} />
          No native gateway destination grant is verified in P1-native. An allowed TCP destination
          would not authorize a tool.
        </div>
      </Panel>
      <Simulator agents={agents} />
      <Modal
        open={!!selectedId}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
        title="Agent authority & recent evidence"
        description="Verified identity context and explicit application-level grants."
        drawer
      >
        {detail.isPending ? (
          <Loading />
        ) : detail.isError ? (
          <ErrorState error={detail.error} />
        ) : (
          detail.data && (
            <>
              <div className="row gap">
                <span className="agent-avatar">
                  <Bot size={23} />
                </span>
                <div>
                  <h3>{detail.data.principal.name}</h3>
                  <p className="mono small muted">{detail.data.principal.id}</p>
                </div>
              </div>
              <dl className="detail-list">
                <KeyValue label="Status">
                  <Status value={detail.data.principal.status} />
                </KeyValue>
                <KeyValue label="Owner">{detail.data.principal.owner}</KeyValue>
                <KeyValue label="Parent">
                  {detail.data.principal.parent_id ?? "No parent / root workload"}
                </KeyValue>
                <KeyValue label="Expires">{time(detail.data.principal.expires_at)}</KeyValue>
                <KeyValue label="Identity epoch">{detail.data.principal.identity_epoch}</KeyValue>
                <KeyValue label="Destination permissions">{detail.data.destination_state}</KeyValue>
              </dl>
              <CodeBlock label="Exact tool and asset grants" value={detail.data.principal.scopes} />
              <h3 className="mini-heading">RECENT DECISIONS</h3>
              {detail.data.decisions.length ? (
                detail.data.decisions.map((item) => (
                  <button className="mini-event" key={item.id} onClick={() => setEvent(item)}>
                    <span>
                      {item.body.attributes.tool ?? item.event_type}
                      <small>{ago(item.received_at)}</small>
                    </span>
                    <Status value={item.outcome} />
                  </button>
                ))
              ) : (
                <Empty title="No decisions yet" />
              )}
              {detail.data.incidents.map((item) => (
                <Link
                  className="notification-item"
                  key={item.id}
                  onClick={() => setSelectedId(null)}
                  to={`/incidents/${item.id}`}
                >
                  <span>
                    {item.number} / {item.title}
                  </span>
                  <ArrowUpRight size={14} />
                </Link>
              ))}
              {admin && (
                <Button
                  variant={detail.data.principal.status === "active" ? "danger" : "secondary"}
                  className="full-width"
                  onClick={() => setConfirmStatus(detail.data.principal)}
                >
                  {detail.data.principal.status === "active"
                    ? "Suspend identity & descendants"
                    : "Reactivate identity for fresh sessions"}
                </Button>
              )}
            </>
          )
        )}
      </Modal>
      <Confirm
        open={!!confirmStatus}
        onOpenChange={(open) => {
          if (!open) setConfirmStatus(null);
        }}
        title={
          confirmStatus?.status === "active"
            ? "Suspend workload authority?"
            : "Reactivate this identity?"
        }
        description={confirmStatus?.name ?? ""}
        consequence={
          confirmStatus?.status === "active"
            ? "This workload and its descendants lose dispatch access. Active sessions terminate and pending approvals are revoked. Existing native gateway tunnels are outside this control."
            : "Fresh, policy-authorized sessions may be created. Old terminated sessions and revoked approvals are not restored."
        }
        busy={status.isPending}
        label={confirmStatus?.status === "active" ? "Suspend identity" : "Reactivate identity"}
        onConfirm={() => status.mutate(undefined, { onSuccess: () => setConfirmStatus(null) })}
      />
      <EvidenceDrawer event={event} onClose={() => setEvent(null)} />
    </div>
  );
}
