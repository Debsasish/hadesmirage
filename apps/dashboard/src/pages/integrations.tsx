import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Boxes,
  CircleAlert,
  FileInput,
  Fingerprint,
  Network,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import { api, post } from "../api";
import {
  Badge,
  Button,
  CodeBlock,
  Empty,
  ErrorState,
  Field,
  KeyValue,
  Loading,
  Modal,
  PageHeading,
  Panel,
  Status,
  time,
} from "../components";
import { useAction, useMe, useWorkspace } from "../state";
import type { ImportedReport, IntegrationsData } from "../types";
import { ImportedReportSummary } from "../components/ai-workflows";
import { TelegramPanel } from "../components/telegram-admin";

export function IntegrationsPage() {
  const me = useMe();
  const { notify } = useWorkspace();
  const [importOpen, setImportOpen] = useState(false);
  const [report, setReport] = useState("");
  const [selected, setSelected] = useState<ImportedReport | null>(null);
  const result = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<IntegrationsData>("/v1/integrations"),
  });
  const ingest = useAction(() => {
    const parsed: unknown = JSON.parse(report);
    return post("/v1/integrations/hades/import", parsed);
  }, "Heuristic report imported with provenance. No policy or grant changed.");
  if (result.isPending)
    return <Loading label="Loading integration configuration and verified capabilities..." />;
  if (result.isError) return <ErrorState error={result.error} />;
  const admin = me.data?.principal.roles.includes("security_admin");
  return (
    <div className="page">
      <PageHeading
        eyebrow="INTEGRATIONS / PROVENANCE OVER PROMISES"
        title="Integrations"
        description="Configured, imported, and runtime-verified are different states."
        actions={
          <Button variant="primary" disabled={!admin} onClick={() => setImportOpen(true)}>
            <FileInput size={15} />
            Import Hades report
          </Button>
        }
      />
      <div className="integration-grid">
        {result.data.items.map((item) => {
          const Icon =
            item.id === "hades" ? Fingerprint : item.id === "gateway" ? Network : Sparkles;
          return (
            <Panel key={item.id} className="integration-card">
              <div className="panel-body">
                <div className="row">
                  <span
                    className={`icon-tile ${item.id === "model" ? "purple" : item.id === "hades" ? "blue" : "neutral"}`}
                  >
                    <Icon size={24} />
                  </span>
                  <span className="grow" />
                  <Status value={item.state} />
                </div>
                <h2>{item.name}</h2>
                <p className="integration-category">{item.category}</p>
                <dl className="detail-list">
                  <KeyValue label="Source / version" mono>
                    {item.version}
                  </KeyValue>
                  <KeyValue label="License / service">{item.license}</KeyValue>
                  <KeyValue label="Last successful operation">
                    {item.last_success
                      ? time(item.last_success)
                      : "No successful runtime operation recorded"}
                  </KeyValue>
                  <KeyValue
                    label={
                      item.id === "model"
                        ? "Connection model"
                        : "Active scanner / gateway connection"
                    }
                  >
                    {item.id === "model"
                      ? "Request-based / no persistent connection"
                      : item.active_connection
                        ? "Verified live connection"
                        : "Not connected"}
                  </KeyValue>
                </dl>
                <h3 className="mini-heading">AVAILABLE CAPABILITIES</h3>
                <ul className="capability-list">
                  {item.capabilities.map((text) => (
                    <li key={text}>
                      <ShieldCheck size={13} />
                      {text}
                    </li>
                  ))}
                </ul>
                {item.id === "model" && (
                  <Link className="button button-secondary" to="/settings">
                    Provider setup & check
                    <ArrowUpRight size={13} />
                  </Link>
                )}
                <h3 className="mini-heading">KNOWN LIMITATIONS</h3>
                <ul className="plain-list">
                  {item.limitations.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
                {item.last_error && (
                  <div className="integration-error">
                    <CircleAlert size={15} />
                    <p>{item.last_error}</p>
                  </div>
                )}
              </div>
            </Panel>
          );
        })}
      </div>
      <TelegramPanel />
      <Panel
        title="Imported evidence"
        subtitle="Reports remain untrusted observations. They never become active permissions."
        action={<Badge dot={false}>Read-only authority</Badge>}
      >
        {result.data.imports.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Version</th>
                  <th>Observations</th>
                  <th>Received</th>
                  <th>
                    <span className="sr-only">Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.data.imports.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>Hades manifest report</strong>
                      <span className="table-meta">Heuristic / not runtime verified</span>
                    </td>
                    <td className="mono small">{item.version.slice(0, 12)}</td>
                    <td>{item.observations.length}</td>
                    <td className="muted">{time(item.created_at)}</td>
                    <td>
                      <Button variant="ghost" onClick={() => setSelected(item)}>
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
          <Empty
            title="No reports imported"
            description="Import a reviewed, versioned Hades manifest report. This does not start a scanner or activate a policy."
          />
        )}
      </Panel>
      <Panel title="Reviewed foundation provenance" action={<Boxes size={17} />}>
        <div className="panel-body">
          <p className="helper">
            Only selected upstream files were reviewed. No uploaded Git history, private settings,
            upstream source, or credentials were copied.
          </p>
          <CodeBlock value={result.data.provenance} />
        </div>
      </Panel>
      <Modal
        open={importOpen}
        onOpenChange={setImportOpen}
        title="Import a versioned Hades report"
        description="JSON only. The adapter validates bounded observations; it never executes scripts, follows report paths, or changes permissions."
        wide
      >
        <Field
          label="Report JSON"
          help="Expected: source_version (40-character commit), tool_count, tools [{name, risk_tier, issues}]."
        >
          <textarea
            className="json-editor"
            rows={12}
            value={report}
            onChange={(event) => setReport(event.target.value)}
            placeholder='{"source_version":"...","tool_count":1,"tools":[{"name":"...","risk_tier":"T3","issues":["..."]}]}'
            maxLength={65536}
            spellCheck={false}
          />
        </Field>
        <label className="file-upload">
          <Upload size={16} />
          <span>Load a JSON file / maximum 64 KiB</span>
          <input
            type="file"
            accept=".json,application/json"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              if (file.size > 65536) {
                notify("Report exceeds the 64 KiB input bound", "error");
                return;
              }
              void file
                .text()
                .then(setReport, (error: unknown) =>
                  notify(
                    error instanceof Error ? error.message : "File could not be read",
                    "error",
                  ),
                );
            }}
          />
        </label>
        {ingest.isError && (
          <p className="error-text" role="alert">
            {ingest.error instanceof SyntaxError
              ? "Invalid JSON. Correct the report before import."
              : ingest.error.message}
          </p>
        )}
        <div className="dialog-actions">
          <Button onClick={() => setImportOpen(false)}>Cancel</Button>
          <Button
            variant="primary"
            busy={ingest.isPending}
            disabled={!report.trim()}
            onClick={() =>
              ingest.mutate(undefined, {
                onSuccess: () => {
                  setImportOpen(false);
                  setReport("");
                },
              })
            }
          >
            Validate & import report
          </Button>
        </div>
      </Modal>
      <Modal
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title="Imported heuristic observations"
        description="Not runtime proof and not an active scanner connection."
        wide
      >
        {selected && (
          <>
            <Badge tone="amber">Untrusted imported evidence</Badge>
            <CodeBlock
              label="Version / source provenance"
              value={{
                version: selected.version,
                digest: selected.digest,
                received_at: selected.created_at,
              }}
            />
            <ImportedReportSummary
              key={selected.id}
              report={selected}
              onObservation={(reference) => {
                const match = /^obs-([1-9][0-9]{0,2})$/.exec(reference);
                const index = match ? Number(match[1]) - 1 : -1;
                if (index < 0 || index >= selected.observations.length) {
                  notify("The referenced local observation is unavailable.", "error");
                  return;
                }
                const element = document.getElementById(
                  `hades-observation-${selected.id}-${index + 1}`,
                );
                if (!element) {
                  notify("The observation could not be focused.", "error");
                  return;
                }
                element.focus();
                element.scrollIntoView({ block: "nearest" });
              }}
            />
            {selected.observations.map((item, index) => (
              <div
                className="import-observation"
                key={index}
                id={`hades-observation-${selected.id}-${index + 1}`}
                tabIndex={-1}
              >
                <h3>
                  {item.name}
                  <Badge tone="amber">{item.risk_tier}</Badge>
                </h3>
                <small>Local observation ref: obs-{index + 1}</small>
                <p>{item.evidence_kind}</p>
                <ul className="plain-list">
                  {item.issues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
                <small>{item.authority}</small>
              </div>
            ))}
          </>
        )}
      </Modal>
    </div>
  );
}
