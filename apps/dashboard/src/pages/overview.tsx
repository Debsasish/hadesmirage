import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, ChevronRight, FlaskConical, LockKeyhole, Play } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, post } from "../api";
import { Badge, Button, CodeBlock, ErrorState, Field, Loading, Modal, Status } from "../components";
import { useAction, useMe, useWorkspace } from "../state";
import type { Scenario, ScenarioResult } from "../types";
export function ScenarioDialog() {
  const { scenarioOpen, setScenarioOpen } = useWorkspace();
  const me = useMe();
  const navigate = useNavigate();
  const [selected, setSelected] = useState("external-probing");
  const [approvalId, setApprovalId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const scenarios = useQuery({
    queryKey: ["scenarios"],
    queryFn: () =>
      api<{
        items: Scenario[];
      }>("/v1/laboratory"),
    enabled: scenarioOpen,
  });
  const run = useAction<ScenarioResult, void>(() =>
    post("/v1/laboratory/run", {
      scenario: selected,
      ...(approvalId ? { approval_id: approvalId } : {}),
    }),
  );
  const needsApproval = ["approved-payment", "approval-substitution"].includes(selected);
  const needsConfirm = ["kill-switch", "approved-payment"].includes(selected);
  const authorized = me.data?.principal.roles.includes("security_admin");
  return (
    <Modal
      open={scenarioOpen}
      onOpenChange={(open) => {
        setScenarioOpen(open);
        if (!open) {
          run.reset();
          setConfirmed(false);
        }
      }}
      title="Run a bounded laboratory scenario"
      description="Real local requests, synthetic records, and an independent backend ledger. No external targets or arbitrary commands."
      wide
    >
      {run.data?.status === "completed" ? (
        <div className="scenario-result">
          <div className="scenario-success">
            <span>
              <Check size={23} />
            </span>
            <div>
              <h3>Execution recorded</h3>
              <p>{scenarios.data?.items.find((item) => item.id === run.data?.scenario)?.title}</p>
            </div>
            <Badge tone="purple">Synthetic laboratory</Badge>
          </div>
          <div className="result-metrics">
            <div>
              <strong>{run.data.backend_effect_delta.production_reads}</strong>
              <span>Production-like reads</span>
            </div>
            <div>
              <strong>{run.data.backend_effect_delta.production_mutations}</strong>
              <span>Production-like mutations</span>
            </div>
            <div>
              <Status value={run.data.session.route_mode} />
              <span>Final session route</span>
            </div>
          </div>
          <p className="helper">
            Counts come from the independent synthetic backend ledger, not model claims. Decoy
            results are simulated.
          </p>
          <CodeBlock label="Recorded response outcomes" value={run.data.outcomes} />
          <div className="dialog-actions">
            {run.data.approval && (
              <Button
                onClick={() => {
                  setScenarioOpen(false);
                  run.reset();
                  navigate("/guardrails?tab=approvals");
                }}
              >
                Review exact approval
                <ChevronRight size={15} />
              </Button>
            )}
            {run.data.incident_id && (
              <Button
                variant="primary"
                onClick={() => {
                  const id = run.data?.incident_id;
                  if (!id) return;
                  setScenarioOpen(false);
                  run.reset();
                  navigate(`/incidents/${id}`);
                }}
              >
                Open incident workbench
                <ArrowRight size={16} />
              </Button>
            )}
            <Button onClick={() => run.reset()}>Run another</Button>
          </div>
        </div>
      ) : (
        <>
          {scenarios.isPending ? (
            <Loading />
          ) : scenarios.isError ? (
            <ErrorState error={scenarios.error} />
          ) : (
            <>
              <Field label="Scenario">
                <select
                  value={selected}
                  onChange={(event) => {
                    setSelected(event.target.value);
                    setConfirmed(false);
                  }}
                  disabled={run.isPending}
                >
                  {scenarios.data.items.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="scenario-description">
                <FlaskConical size={21} />
                <div>
                  <h3>{scenarios.data.items.find((item) => item.id === selected)?.title}</h3>
                  <p>{scenarios.data.items.find((item) => item.id === selected)?.description}</p>
                  <div className="row">
                    {scenarios.data.items
                      .find((item) => item.id === selected)
                      ?.test_ids.map((id) => (
                        <Badge key={id} dot={false}>
                          {id}
                        </Badge>
                      ))}
                  </div>
                </div>
              </div>
              {needsApproval && (
                <Field
                  label="Exact approval ID"
                  help="Use a laboratory approval from Guardrails & policies. Changed arguments are never authorized."
                >
                  <input
                    value={approvalId}
                    onChange={(event) => setApprovalId(event.target.value)}
                    placeholder="Approval UUID"
                  />
                </Field>
              )}
              {needsConfirm && (
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                  />
                  <span>
                    {selected === "kill-switch"
                      ? "Terminate all active tenant decoys and disable new engagements. Production access will not be restored."
                      : "Execute the exact reviewed change once against synthetic backend records."}
                  </span>
                </label>
              )}
              {!authorized && (
                <div className="callout callout-amber">
                  <LockKeyhole size={18} />
                  <div>
                    A security administrator must run laboratory scenarios. Sign in with that
                    separate local fixture identity.
                  </div>
                </div>
              )}
              {run.isError && (
                <p className="error-text" role="alert">
                  {run.error.message}
                </p>
              )}
              <div className="dialog-actions">
                <span className="helper">No network scans. No real payments.</span>
                <Button
                  variant="primary"
                  busy={run.isPending}
                  disabled={
                    !authorized || (needsApproval && !approvalId) || (needsConfirm && !confirmed)
                  }
                  onClick={() => run.mutate()}
                >
                  <Play size={15} />
                  Run scenario
                </Button>
              </div>
            </>
          )}
        </>
      )}
    </Modal>
  );
}
export { OverviewPage } from "./operations-overview";
