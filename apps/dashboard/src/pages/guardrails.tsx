import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  ClipboardCheck,
  Code2,
  Eye,
  FileCheck2,
  FlaskConical,
  GitCompareArrows,
  LockKeyhole,
  Plus,
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
  Field,
  KeyValue,
  Loading,
  Modal,
  PageHeading,
  Panel,
  Status,
  Tabs,
  time,
} from "../components";
import { useAction, useMe } from "../state";
import type { Approval, PolicyDocument, PolicyVersion, Rule, ScenarioResult } from "../types";

function PolicyEditor({
  active,
  count,
  close,
}: {
  active: PolicyVersion;
  count: number;
  close: () => void;
}) {
  const [draft, setDraft] = useState<PolicyDocument>({
    ...structuredClone(active.document),
    version: `policy-demo-v${count + 1}`,
  });
  const [selectedRule, setSelectedRule] = useState(0);
  const [mode, setMode] = useState("form");
  const [advanced, setAdvanced] = useState(JSON.stringify(draft, null, 2));
  const [compare, setCompare] = useState(false);
  const create = useAction<PolicyVersion, void>(() => {
    const body: unknown = mode === "structured" ? JSON.parse(advanced) : draft;
    return post("/v1/policies", body);
  }, "Immutable policy draft created. Test and obtain separate review before activation.");
  const rule = draft.rules[selectedRule];
  function updateRule(change: Partial<typeof rule>) {
    setDraft({
      ...draft,
      rules: draft.rules.map((item, index) =>
        index === selectedRule ? { ...item, ...change } : item,
      ),
    });
  }
  return (
    <>
      <Tabs
        value={mode}
        onChange={(value) => {
          setMode(value);
          if (value === "structured") setAdvanced(JSON.stringify(draft, null, 2));
        }}
        tabs={[
          { value: "form", label: "Human-readable editor" },
          { value: "structured", label: "Advanced JSON" },
        ]}
      />
      <div className="editor-body">
        {mode === "structured" ? (
          <Field
            label="Policy JSON"
            help="The full document is schema-validated by the server. Unknown fields and duplicate rule IDs are rejected."
          >
            <textarea
              className="json-editor"
              rows={18}
              value={advanced}
              onChange={(event) => setAdvanced(event.target.value)}
              spellCheck={false}
            />
          </Field>
        ) : (
          <>
            <div className="form-grid">
              <Field label="New immutable version">
                <input
                  value={draft.version}
                  required
                  maxLength={100}
                  onChange={(event) => setDraft({ ...draft, version: event.target.value })}
                />
              </Field>
              <Field label="Default effect">
                <input value="Deny / fixed" readOnly />
              </Field>
            </div>
            <Field label="Rule">
              <select
                value={selectedRule}
                onChange={(event) => setSelectedRule(Number(event.target.value))}
              >
                {draft.rules.map((item, index) => (
                  <option value={index} key={item.id}>
                    {item.id} / {item.tool}
                  </option>
                ))}
              </select>
            </Field>
            <div className="rule-editor">
              <div className="form-grid">
                <Field label="Effect">
                  <select
                    value={rule.effect}
                    onChange={(event) =>
                      updateRule({ effect: event.target.value === "deny" ? "deny" : "allow" })
                    }
                  >
                    <option value="allow">Allow within exact workload scope</option>
                    <option value="deny">Explicit deny / takes precedence</option>
                  </select>
                </Field>
                <Field label="Resource prefix">
                  <input
                    className="mono"
                    value={rule.resource_prefix}
                    onChange={(event) => updateRule({ resource_prefix: event.target.value })}
                  />
                </Field>
                <Field label="Tool">
                  <input className="mono" readOnly value={rule.tool} />
                </Field>
                <Field label="Actions">
                  <input
                    className="mono"
                    value={rule.actions.join(", ")}
                    onChange={(event) =>
                      updateRule({
                        actions: event.target.value
                          .split(",")
                          .map((value) => value.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </Field>
              </div>
              <Field
                label="Policy principal IDs"
                help="Comma separated. These do not replace exact resource grants or delegation checks."
              >
                <input
                  className="mono"
                  value={rule.principal_ids.join(", ")}
                  onChange={(event) =>
                    updateRule({
                      principal_ids: event.target.value
                        .split(",")
                        .map((value) => value.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </Field>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={rule.approval_required}
                  onChange={(event) => updateRule({ approval_required: event.target.checked })}
                />
                <span>Require an exact, one-time action approval</span>
              </label>
            </div>
          </>
        )}
        <button className="text-link" onClick={() => setCompare((value) => !value)}>
          <GitCompareArrows size={15} />
          {compare ? "Hide change comparison" : "Compare with active policy"}
        </button>
        {compare && (
          <div className="comparison-grid">
            <CodeBlock label="Current active version" value={active.document} />
            <CodeBlock
              label="Proposed draft (form state)"
              value={mode === "structured" ? advanced : draft}
            />
          </div>
        )}
        {create.isError && (
          <p className="error-text" role="alert">
            {create.error instanceof SyntaxError
              ? "Invalid JSON. Correct the structured document before saving."
              : create.error.message}
          </p>
        )}
      </div>
      <div className="dialog-actions">
        <span className="helper">Draft does not grant authority.</span>
        <Button onClick={close}>Cancel</Button>
        <Button
          variant="primary"
          busy={create.isPending}
          onClick={() => create.mutate(undefined, { onSuccess: close })}
        >
          <Plus size={14} />
          Save draft
        </Button>
      </div>
    </>
  );
}

function Policies() {
  const me = useMe();
  const [selected, setSelected] = useState<string | null>(null);
  const [editor, setEditor] = useState(false);
  const [confirm, setConfirm] = useState<{ policy: PolicyVersion; action: string } | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const result = useQuery({
    queryKey: ["policies"],
    queryFn: () => api<{ items: PolicyVersion[] }>("/v1/policies"),
  });
  const workflow = useAction<PolicyVersion, { policy: PolicyVersion; action: string }>(
    (value) =>
      post(`/v1/policies/${encodeURIComponent(value.policy.id)}/workflow`, {
        action: value.action,
        expected_digest: value.policy.digest,
      }),
    "Policy workflow result recorded.",
  );
  if (result.isPending) return <Loading />;
  if (result.isError) return <ErrorState error={result.error} />;
  const active = result.data.items.find((item) => item.status === "active") ?? result.data.items[0];
  const current = result.data.items.find((item) => item.id === selected) ?? active;
  const admin = me.data?.principal.roles.includes("security_admin");
  const approver = me.data?.principal.roles.includes("approver");
  return (
    <>
      <div className="policy-lifecycle">
        <span>
          <FileCheck2 size={17} />
          Draft
        </span>
        <ArrowRight size={13} />
        <span>Validate & test</span>
        <ArrowRight size={13} />
        <span>Separate review</span>
        <ArrowRight size={13} />
        <span>
          <ShieldCheck size={16} />
          Activate immutable version
        </span>
      </div>
      <div className="policy-grid">
        <Panel
          title="Version history"
          action={
            admin ? (
              <Button variant="ghost" onClick={() => setEditor(true)}>
                <Plus size={14} />
                Draft
              </Button>
            ) : undefined
          }
        >
          <div className="policy-list">
            {result.data.items.map((policy) => (
              <button
                key={policy.id}
                onClick={() => setSelected(policy.id)}
                className={policy.id === current.id ? "selected" : ""}
              >
                <div>
                  <strong className="mono">{policy.version}</strong>
                  <Status value={policy.status} />
                </div>
                <small>
                  {policy.document.rules.length} rules / {time(policy.created_at)}
                </small>
                <span className="mono tiny muted">{policy.digest.slice(0, 24)}...</span>
              </button>
            ))}
          </div>
        </Panel>
        <Panel
          title={current.version}
          subtitle={`Default deny / ${current.document.rules.length} rules / immutable content`}
          action={
            <button className="text-link" onClick={() => setAdvanced((value) => !value)}>
              <Code2 size={14} />
              {advanced ? "Readable view" : "Structured view"}
            </button>
          }
        >
          <div className="panel-body">
            <div className="row wrap">
              <Status value={current.status} />
              <Badge tone={current.tested ? "teal" : "amber"}>
                {current.tested ? "Fixtures passed" : "Not tested"}
              </Badge>
              <Badge dot={false}>
                {current.reviewed_by
                  ? `Reviewed by ${current.reviewed_by}`
                  : "Separate review required"}
              </Badge>
            </div>
            {advanced ? (
              <CodeBlock value={current.document} />
            ) : (
              <div className="policy-rules">
                {current.document.rules.map((rule) => (
                  <article key={rule.id}>
                    <span className={`rule-effect effect-${rule.effect}`}>
                      {rule.effect === "deny" ? <LockKeyhole size={16} /> : <Check size={16} />}
                    </span>
                    <div>
                      <h3>
                        {rule.id}
                        <Badge tone={rule.effect === "deny" ? "red" : "teal"}>{rule.effect}</Badge>
                        {rule.approval_required && <Badge tone="amber">Approval required</Badge>}
                      </h3>
                      <p className="mono">
                        {rule.tool} / {rule.actions.join(", ")}
                      </p>
                      <small>
                        Resources: {rule.resource_prefix} / principals:{" "}
                        {rule.principal_ids.join(", ")}
                      </small>
                    </div>
                  </article>
                ))}
              </div>
            )}
            <CodeBlock label="Exact content digest / SHA-256" value={current.digest} />
            <div className="policy-actions">
              {current.status === "draft" && (
                <>
                  <Button
                    busy={workflow.isPending}
                    disabled={!admin}
                    onClick={() => workflow.mutate({ policy: current, action: "test" })}
                  >
                    <FlaskConical size={14} />
                    Test fixtures
                  </Button>
                  <Button
                    disabled={
                      !approver || !current.tested || current.created_by === me.data?.principal.id
                    }
                    onClick={() => setConfirm({ policy: current, action: "review" })}
                  >
                    <Eye size={14} />
                    Review exact version
                  </Button>
                </>
              )}
              {current.status === "reviewed" && admin && (
                <>
                  <Button
                    variant="primary"
                    onClick={() => setConfirm({ policy: current, action: "activate" })}
                  >
                    <ShieldCheck size={14} />
                    Activate reviewed version
                  </Button>
                  <Button onClick={() => setConfirm({ policy: current, action: "rollback" })}>
                    Rollback to this version
                  </Button>
                </>
              )}
              {current.status === "active" && admin && (
                <Button onClick={() => setEditor(true)}>
                  <Plus size={14} />
                  Create new draft
                </Button>
              )}
            </div>
            {workflow.data?.id === current.id && workflow.data.fixture_results && (
              <div className="fixture-results">
                {workflow.data.fixture_results.map((item, index) => (
                  <div key={index}>
                    <Status value={item.passed ? "success" : "failure"} />
                    <span className="mono small">{item.tool}</span>
                    <span>
                      Expected {item.expected} / actual {item.actual}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p className="helper">
              Activation invalidates approvals bound to older policy versions. A model cannot review
              or activate a policy.
            </p>
          </div>
        </Panel>
      </div>
      <Modal
        open={editor}
        onOpenChange={setEditor}
        title="Create a reviewed-policy candidate"
        description="Changes are saved as a new draft. Active policy content is never edited in place."
        wide
      >
        {editor && (
          <PolicyEditor
            active={active}
            count={result.data.items.length}
            close={() => setEditor(false)}
          />
        )}
      </Modal>
      <Confirm
        open={!!confirm}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
        title={
          confirm?.action === "review"
            ? "Review this exact policy?"
            : "Change the active policy version?"
        }
        description={confirm?.policy.version ?? ""}
        consequence={
          confirm?.action === "review"
            ? `You are attesting review of content digest ${confirm.policy.digest}. This does not activate the version.`
            : "The reviewed version becomes authoritative for new operations. Old-policy approvals become unusable. Authorization and deception boundaries remain active."
        }
        danger={false}
        label={
          confirm?.action === "review" ? "Record separate review" : "Activate reviewed version"
        }
        busy={workflow.isPending}
        onConfirm={() => {
          if (confirm) workflow.mutate(confirm, { onSuccess: () => setConfirm(null) });
        }}
      />
    </>
  );
}

function Approvals() {
  const me = useMe();
  const result = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api<{ items: Approval[] }>("/v1/approvals"),
  });
  const [selected, setSelected] = useState<{
    approval: Approval;
    decision: "approve" | "reject";
  } | null>(null);
  const [execution, setExecution] = useState<Approval | null>(null);
  const review = useAction(
    (value: { approval: Approval; decision: "approve" | "reject" }) =>
      post(`/v1/approvals/${value.approval.id}/decision`, {
        decision: value.decision,
        expected_digest: value.approval.digest,
      }),
    "Exact approval decision recorded.",
  );
  const execute = useAction<ScenarioResult, Approval>(
    (approval) =>
      post("/v1/laboratory/run", { scenario: "approved-payment", approval_id: approval.id }),
    "Reviewed synthetic backend action executed. Inspect the ledger for its outcome.",
  );
  if (result.isPending) return <Loading />;
  if (result.isError) return <ErrorState error={result.error} />;
  const approver = me.data?.principal.roles.includes("approver");
  const admin = me.data?.principal.roles.includes("security_admin");
  return (
    <>
      <div className="callout callout-amber">
        <ClipboardCheck size={19} />
        <div>
          <strong>One approval. One exact action.</strong>
          <p>
            Review the acting identity, resource, arguments, policy version, expiry and canonical
            digest. Requesters cannot approve their own actions.
          </p>
        </div>
      </div>
      {!result.data.items.length ? (
        <Empty
          title="No actions awaiting review"
          description="Run the unapproved payment-change laboratory scenario to create an exact review request."
        />
      ) : (
        <div className="approval-grid">
          {result.data.items.map((approval) => {
            const expired = new Date(approval.expires_at).getTime() <= Date.now();
            const own =
              approval.requester_id === me.data?.principal.id ||
              approval.principal_id === me.data?.principal.id;
            const canReview = approver && !own && !expired && approval.status === "pending";
            return (
              <Panel
                key={approval.id}
                title="Payment-change request"
                action={
                  <Status
                    value={
                      expired && ["pending", "approved"].includes(approval.status)
                        ? "expired"
                        : approval.status
                    }
                  />
                }
              >
                <div className="panel-body">
                  <dl className="detail-list">
                    <KeyValue label="Acting agent" mono>
                      {approval.principal_id}
                    </KeyValue>
                    <KeyValue label="Requested by">{approval.requester_id}</KeyValue>
                    <KeyValue label="Exact action" mono>
                      {approval.invocation.tool} / {approval.invocation.action}
                    </KeyValue>
                    <KeyValue label="Resource" mono>
                      {approval.invocation.resource}
                    </KeyValue>
                    <KeyValue label="Policy" mono>
                      {approval.policy_version}
                    </KeyValue>
                    <KeyValue label="Expires">{time(approval.expires_at)}</KeyValue>
                  </dl>
                  <CodeBlock label="Exact typed arguments" value={approval.invocation.arguments} />
                  <CodeBlock
                    label="Request digest / NFC JSON v1 + SHA-256"
                    value={approval.digest}
                  />
                  <p className="mono tiny muted">Approval: {approval.id}</p>
                  <div className="approval-actions">
                    {canReview ? (
                      <>
                        <Button
                          variant="primary"
                          onClick={() => setSelected({ approval, decision: "approve" })}
                        >
                          <Check size={15} />
                          Approve one execution
                        </Button>
                        <Button onClick={() => setSelected({ approval, decision: "reject" })}>
                          Reject
                        </Button>
                      </>
                    ) : approval.status === "pending" && !expired ? (
                      <p className="helper">
                        {own
                          ? "You requested this action. A separate reviewer is required."
                          : "Sign in as the independent approver to review this request."}
                      </p>
                    ) : null}
                    {admin && approval.status === "approved" && !expired && (
                      <Button onClick={() => setExecution(approval)}>
                        <FlaskConical size={14} />
                        Execute reviewed lab action
                      </Button>
                    )}
                  </div>
                  {approval.approver_id && (
                    <p className="helper">
                      Reviewed by {approval.approver_id}. An approval does not itself mean execution
                      occurred.
                    </p>
                  )}
                </div>
              </Panel>
            );
          })}
        </div>
      )}
      <Confirm
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={
          selected?.decision === "approve"
            ? "Approve this exact synthetic change?"
            : "Reject this action?"
        }
        description={selected?.approval.invocation.resource ?? ""}
        consequence={
          selected?.decision === "approve"
            ? "This authorizes one payment-account change against the synthetic backend, with exactly the shown arguments and digest. It cannot authorize substituted arguments or another policy version."
            : "The action will remain unauthorized. This does not modify the backend."
        }
        danger={selected?.decision === "reject"}
        label={selected?.decision === "approve" ? "Approve exact action" : "Reject action"}
        busy={review.isPending}
        onConfirm={() => {
          if (selected) review.mutate(selected, { onSuccess: () => setSelected(null) });
        }}
      />
      <Confirm
        open={!!execution}
        onOpenChange={(open) => {
          if (!open) setExecution(null);
        }}
        title="Execute the reviewed laboratory action?"
        description="This dispatches an actual request to the independent synthetic backend."
        consequence="The synthetic supplier account reference will change once. The exact approval is consumed; changing routing later does not undo this committed record."
        danger={false}
        label="Execute synthetic change once"
        busy={execute.isPending}
        onConfirm={() => {
          if (execution) execute.mutate(execution, { onSuccess: () => setExecution(null) });
        }}
      />
    </>
  );
}

function DetectionRules() {
  const result = useQuery({
    queryKey: ["rules"],
    queryFn: () => api<{ items: Rule[]; version: string }>("/v1/detection/rules"),
  });
  if (result.isPending) return <Loading />;
  if (result.isError) return <ErrorState error={result.error} />;
  return (
    <>
      <div className="callout">
        <ShieldCheck size={18} />
        <div>
          Correlation uses server receipt time, authenticated source context and verified session
          keys. Shared IPs are not treated as a single identity.
        </div>
      </div>
      <div className="rules-grid">
        {result.data.items.map((rule) => (
          <Panel key={rule.id}>
            <div className="panel-body">
              <div className="row">
                <Badge tone="blue" dot={false}>
                  {rule.id}
                </Badge>
                <span className="grow" />
                <Status value={rule.severity} />
              </div>
              <h2>{rule.name}</h2>
              <p>{rule.threshold}</p>
              <dl className="compact-details">
                <KeyValue label="Response">{rule.response}</KeyValue>
                <KeyValue label="Rule version" mono>
                  {result.data.version}
                </KeyValue>
              </dl>
            </div>
          </Panel>
        ))}
      </div>
    </>
  );
}

export function GuardrailsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "policies";
  return (
    <div className="page">
      <PageHeading
        eyebrow="ENFORCEMENT / VERSIONED AUTHORITY"
        title="Access rules"
        description="Deny by default. Review changes. Bind approvals to the exact action."
        actions={
          <Badge tone="teal">
            <ShieldCheck size={12} />
            Outside the model
          </Badge>
        }
      />
      <Tabs
        value={tab}
        onChange={(value) => setParams({ tab: value })}
        tabs={[
          {
            value: "policies",
            label: (
              <>
                <SlidersHorizontal size={15} />
                Policies
              </>
            ),
          },
          {
            value: "approvals",
            label: (
              <>
                <ClipboardCheck size={15} />
                Approval queue
              </>
            ),
          },
          {
            value: "rules",
            label: (
              <>
                <ShieldCheck size={15} />
                Detection rules
              </>
            ),
          },
        ]}
      />
      {tab === "approvals" ? <Approvals /> : tab === "rules" ? <DetectionRules /> : <Policies />}
    </div>
  );
}
