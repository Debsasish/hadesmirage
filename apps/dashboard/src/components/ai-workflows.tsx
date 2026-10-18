import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CircleAlert,
  FileSearch,
  MessageSquare,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api, post } from "../api";
import {
  Badge,
  Button,
  CodeBlock,
  Confirm,
  ErrorState,
  Field,
  KeyValue,
  Loading,
  Panel,
  Status,
  short,
  time,
} from "../components";
import { useAction, useMe } from "../state";
import type {
  AIGeneration,
  AIProviderCheck,
  AIProviderStatus,
  AIRequest,
  CaseAnswer,
  CaseDetail,
  ImportedReport,
  ModelCatalogue,
  ReportSummary,
  ReportSummaryHistory,
} from "../types";

export function useAIStatus() {
  return useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api<AIProviderStatus>("/v1/ai"),
    staleTime: 30_000,
    retry: false,
  });
}

function Attribution({ value }: { value: AIGeneration }) {
  return (
    <div className="ai-attribution">
      <Badge tone="purple" dot={false}>
        {value.provider === "fixture-investigator-v1"
          ? "Fixture output / not live AI"
          : value.provider}
      </Badge>
      <span>{time(value.generated_at)}</span>
      <span>
        {value.tokens === null ? "Token usage not reported" : `${value.tokens} reported tokens`}
      </span>
    </div>
  );
}

function RequestState({ request }: { request: AIRequest<unknown> }) {
  return (
    <div className="callout callout-amber">
      <CircleAlert size={16} />
      <p>
        {request.state === "pending"
          ? `A bounded request is pending until ${time(request.deadline_at)}.`
          : request.state === "unknown"
            ? "The request deadline passed; provider outcome is unknown."
            : `Response unavailable: ${request.error_code ?? "No completed response"}.`}{" "}
        No automatic resend or access change occurred.
      </p>
    </div>
  );
}

const REGIONS = [
  "global",
  "us-central1",
  "us-east4",
  "europe-west1",
  "europe-west4",
  "asia-south1",
  "asia-southeast1",
];

export function AIConfigForm({ status }: { status: AIProviderStatus }) {
  const [provider, setProvider] = useState<string>(status.mode);
  const [project, setProject] = useState(status.project ?? "");
  const [location, setLocation] = useState(status.region);
  const [model, setModel] = useState(status.model ?? "gemini-3.8-flash");
  const [egress, setEgress] = useState(status.egress_approved);
  const [acknowledged, setAcknowledged] = useState(status.egress_approved);
  const [autoTriage, setAutoTriage] = useState(status.auto_triage);
  const [wording, setWording] = useState(status.decoy_wording_enabled);
  const catalogue = useQuery({
    queryKey: ["ai-models", status.settings_version],
    queryFn: () => api<ModelCatalogue>("/v1/ai/models"),
    retry: false,
  });
  const save = useAction(
    () =>
      api("/v1/ai/config", {
        method: "PUT",
        body: JSON.stringify({
          provider,
          project: provider === "gemini" ? project.trim() : "",
          location,
          model: provider === "gemini" ? model.trim() : "",
          egress_approved: provider === "gemini" && egress,
          acknowledge_egress: provider === "gemini" && egress && acknowledged,
          auto_triage: autoTriage,
          decoy_wording: wording,
          expected_version: status.settings_version,
        }),
      }),
    "AI settings saved and applied. No credentials were stored in the browser.",
  );
  const gemini = provider === "gemini";
  return (
    <form
      className="ai-config-form"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h3>Choose the AI</h3>
      <Field label="AI provider">
        <select value={provider} onChange={(event) => setProvider(event.target.value)}>
          <option value="fixture">Demo mode — built-in answers, no AI calls</option>
          <option value="gemini">
            {status.api_key_configured
              ? "Google Gemini (server API key)"
              : "Google Gemini (Vertex AI)"}
          </option>
          <option value="unavailable">Turn AI off</option>
        </select>
      </Field>
      {gemini && (
        <>
          <div className="field-row">
            <Field
              label="Google Cloud project ID"
              help={
                status.api_key_configured
                  ? "Optional: the server already has a Gemini API key (hidden)."
                  : "Lowercase, 6–30 characters. Uses the server's Google workload identity."
              }
            >
              <input
                value={project}
                onChange={(event) => setProject(event.target.value)}
                placeholder="my-security-project"
                maxLength={30}
                required={!status.api_key_configured}
              />
            </Field>
            <Field label="Region">
              <select value={location} onChange={(event) => setLocation(event.target.value)}>
                {REGIONS.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field
            label="Gemini model"
            help={catalogue.data?.note ?? "Pick a model your project can use."}
          >
            <input
              list="gemini-models"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              maxLength={120}
              required
            />
          </Field>
          <datalist id="gemini-models">
            {catalogue.data?.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label} — {item.note}
              </option>
            ))}
          </datalist>
          <Button
            type="button"
            variant="ghost"
            busy={catalogue.isFetching}
            onClick={() => void catalogue.refetch()}
          >
            <Sparkles size={14} />
            {catalogue.data?.source === "live"
              ? "Refresh available models"
              : "Discover available models"}
          </Button>
          <label className="check-row">
            <input
              type="checkbox"
              checked={egress}
              onChange={(event) => setEgress(event.target.checked)}
            />
            <span>
              Allow Mirage to send redacted case evidence to Gemini (may incur Google Cloud
              charges).
            </span>
          </label>
          {egress && (
            <label className="check-row">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              <span>
                I confirm this project is approved for this data. Credentials stay in the
                server&apos;s Google workload identity, never in the browser.
              </span>
            </label>
          )}
        </>
      )}
      <label className="check-row">
        <input
          type="checkbox"
          checked={autoTriage}
          onChange={(event) => setAutoTriage(event.target.checked)}
        />
        <span>
          Let AI automatically review every new issue (advice only — rules still decide blocking and
          honeypot moves).
        </span>
      </label>
      <label className="check-row">
        <input
          type="checkbox"
          checked={wording}
          onChange={(event) => setWording(event.target.checked)}
        />
        <span>
          Let AI write the honeypot&apos;s fake replies (always falls back to safe built-in text).
        </span>
      </label>
      {save.isError && (
        <p className="error-text" role="alert">
          {save.error.message}
        </p>
      )}
      <div className="row wrap">
        <Button
          type="submit"
          variant="primary"
          busy={save.isPending}
          disabled={gemini && egress && !acknowledged}
        >
          Save AI settings
        </Button>
        <span className="helper">
          Version {status.settings_version} ·{" "}
          {status.settings_source === "portal"
            ? `changed by ${status.settings_updated_by}`
            : "from server environment"}
        </span>
      </div>
    </form>
  );
}

export function AIProviderPanel() {
  const me = useMe();
  const result = useAIStatus();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const check = useAction(
    (allowLive: boolean) => post<AIProviderCheck>("/v1/ai/check", { allow_live: allowLive }),
    "Bounded provider check recorded. This is not continuous health monitoring.",
  );
  const data = result.data;
  const admin = me.data?.principal.roles.includes("security_admin");
  return (
    <Panel
      title="AI provider & safeguards"
      action={data ? <Status value={data.state} /> : <Sparkles size={17} />}
    >
      <div className="panel-body ai-provider">
        {result.isPending ? (
          <Loading label="Reading AI provider configuration..." />
        ) : result.isError ? (
          <ErrorState error={result.error} retry={() => void result.refetch()} />
        ) : data ? (
          <>
            <div className="callout">
              <ShieldCheck size={17} />
              <div>
                {data.mode === "fixture"
                  ? "Fixture mode is deterministic demonstration output, not live AI. No cloud request is made."
                  : "AI is advisory only. It has no tools, signer, shell, policy or routing authority."}
              </div>
            </div>
            <dl className="detail-list">
              <KeyValue label="Provider">{data.provider}</KeyValue>
              <KeyValue label="Live model">{data.model ?? "Not configured"}</KeyValue>
              <KeyValue label="Credential">
                {data.credential === "api-key"
                  ? `Server API key (hidden) · ${data.endpoint}`
                  : data.credential === "workload-identity"
                    ? `Google workload identity · ${data.endpoint}`
                    : "None configured"}
              </KeyValue>
              <KeyValue label="Configured region">{data.region}</KeyValue>
              <KeyValue label="Model egress">
                {data.egress_approved ? "Operator-approved" : "Not approved"}
              </KeyValue>
              <KeyValue label="Tenant request reservations">
                {data.call_reservations_used} / {data.tenant_call_budget}
              </KeyValue>
              <KeyValue label="Shared per-case limit">
                {data.case_call_budget} investigations and questions
              </KeyValue>
              <KeyValue label="Pending reservations">
                {data.pending_requests} / {data.max_pending}
              </KeyValue>
              <KeyValue label="Request bounds">
                {data.timeout_seconds}s SDK timeout / {data.max_output_tokens} output tokens
              </KeyValue>
              <KeyValue label="Reported usage">
                {data.reported_tokens.toLocaleString()} tokens
              </KeyValue>
              <KeyValue label="Usage not reported">
                {data.requests_without_reported_usage} requests
              </KeyValue>
              <KeyValue label="Synthetic wording">
                {data.decoy_wording_enabled ? "Enabled with static fallback" : "Disabled"}
              </KeyValue>
            </dl>
            <p className="helper">
              Reservations include failed and fixture requests. Reported tokens are not a complete
              billing total when usage is unavailable. Provider credentials are never readable here.
            </p>
            {data.last_check && (
              <div className="ai-check-result">
                <div className="row wrap">
                  <strong>Last check</strong>
                  <Status value={data.last_check.state} />
                  <span>{time(data.last_check.completed_at ?? data.last_check.started_at)}</span>
                </div>
                {data.last_check.output ? (
                  <p>
                    {data.last_check.output.live
                      ? "One synthetic request passed against the configured live provider."
                      : "Fixture check passed. This does not verify Gemini, credentials or live inference."}
                  </p>
                ) : (
                  <RequestState request={data.last_check} />
                )}
              </div>
            )}
            <Button
              busy={check.isPending}
              disabled={
                !admin ||
                !data.can_generate ||
                data.calls_remaining === 0 ||
                data.pending_requests >= data.max_pending
              }
              onClick={() => (data.mode === "fixture" ? check.mutate(false) : setConfirmOpen(true))}
            >
              <ShieldCheck size={15} />
              {data.mode === "fixture" ? "Run fixture check" : "Check configured AI"}
            </Button>
            {!admin && (
              <p className="helper">A security administrator is required to run provider checks.</p>
            )}
            {!data.can_generate && (
              <p className="helper">
                Complete server-side provider configuration and egress approval before generating AI
                output.
              </p>
            )}
            <details className="ai-setup">
              <summary>Configure live Gemini</summary>
              <p>
                Configure approved workload credentials outside this app, then set these values in
                the ignored local .env and restart the native launcher. Select an available approved
                model; no model availability is assumed. Start with a small approved call budget.
              </p>
              <CodeBlock
                value={[
                  "MIRAGE_MODEL_PROVIDER=gemini",
                  "MIRAGE_GEMINI_PROJECT=<approved-project>",
                  "MIRAGE_GEMINI_LOCATION=global",
                  "MIRAGE_GEMINI_MODEL=<approved-available-model>",
                  "MIRAGE_MODEL_EGRESS_APPROVED=true",
                  `MIRAGE_MODEL_CALL_BUDGET=${Math.min(data.call_reservations_used + 3, 10000)}`,
                ].join("\n")}
              />
              <p className="helper">
                No keys are entered in the browser. Live requests may incur provider charges. The
                check sends synthetic data only; case questions send bounded, redacted case
                evidence. The example total cap includes existing reservations and permits up to
                three additional requests; change it only to match your approved budget.
              </p>
            </details>
            <p className="helper">{data.check_scope}</p>
            {admin && <AIConfigForm key={data.settings_version} status={data} />}
          </>
        ) : null}
      </div>
      <Confirm
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Send one synthetic AI check?"
        description="Uses the environment-configured provider and approved workload identity."
        consequence="Consumes one tenant request reservation and may incur provider charges. No case evidence or scanner text is sent. No tool, permission or routing action can be executed."
        danger={false}
        label="Send synthetic check"
        busy={check.isPending}
        onConfirm={() => check.mutate(true, { onSuccess: () => setConfirmOpen(false) })}
      />
    </Panel>
  );
}

export function CaseAssistant({
  detail,
  onEvidence,
}: {
  detail: CaseDetail;
  onEvidence: (reference: string) => void;
}) {
  const provider = useAIStatus();
  const [question, setQuestion] = useState("");
  const ask = useAction(
    (value: string) =>
      post<CaseAnswer>(`/v1/incidents/${detail.incident.id}/assistant`, {
        question: value,
        expected_version: detail.incident.version,
      }),
    "Advisory case response recorded. No access or route changed.",
  );
  const blocked =
    !provider.data?.can_generate ||
    provider.data.calls_remaining === 0 ||
    detail.model_budget.remaining === 0;
  return (
    <Panel
      title="Ask this case"
      subtitle="Read-only questions with cited observations. Responses are shared with workspace analysts."
      action={<Badge dot={false}>{detail.model_budget.remaining} case requests left</Badge>}
    >
      <div className="panel-body ai-assistant">
        {provider.isError && (
          <ErrorState error={provider.error} retry={() => void provider.refetch()} />
        )}
        <p className="helper">
          Uses up to 20 recent linked observations, not prior model answers or unrestricted
          workspace data. Every response is untrusted advisory text. Investigations and questions
          share this case's {detail.model_budget.limit}-request limit.
        </p>
        {provider.data?.mode === "fixture" && (
          <Badge tone="purple" dot={false}>
            Fixture responses / not live AI
          </Badge>
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!blocked && question.trim().length >= 8)
              ask.mutate(question.trim(), { onSuccess: () => setQuestion("") });
          }}
        >
          <Field
            label="Question about this case"
            help="Do not include credentials, private source code or production data. Maximum 1,000 characters."
          >
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              minLength={8}
              maxLength={1000}
              disabled={ask.isPending}
              placeholder="What do these denials establish, and what evidence is missing?"
              required
            />
          </Field>
          <div className="ai-suggestions">
            {["What was denied?", "What evidence is missing?", "What should be reviewed next?"].map(
              (text) => (
                <button
                  key={text}
                  type="button"
                  disabled={ask.isPending}
                  onClick={() => setQuestion(text)}
                >
                  {text}
                </button>
              ),
            )}
          </div>
          <div className="ai-form-actions">
            <span>{question.length} / 1,000</span>
            <Button
              type="submit"
              variant="primary"
              busy={ask.isPending}
              disabled={blocked || question.trim().length < 8}
            >
              <MessageSquare size={15} />
              {provider.data?.mode === "fixture" ? "Generate fixture answer" : "Ask configured AI"}
            </Button>
          </div>
        </form>
        {blocked && (
          <p className="helper">
            Provider configuration or the remaining case/tenant budget currently prevents a new
            response. Deterministic evidence remains available.
          </p>
        )}
        {ask.isError && (
          <p className="error-text" role="alert">
            {ask.error.message}
          </p>
        )}
        <div className="ai-history">
          {detail.assistant.length === 0 ? (
            <p className="helper">
              No case questions recorded yet. Nothing is sent until you submit.
            </p>
          ) : (
            detail.assistant.map((record, index) => (
              <details key={record.id} className="ai-record" open={index === 0}>
                <summary>
                  <span>{record.question}</span>
                  <Status value={record.state} />
                </summary>
                <div className="ai-record-body">
                  {record.output && record.state === "succeeded" ? (
                    <>
                      <Attribution value={record.output} />
                      {record.resource_version !== detail.incident.version && (
                        <Badge tone="amber">
                          Earlier case snapshot / v{record.resource_version}
                        </Badge>
                      )}
                      <p className="ai-answer">{record.output.answer}</p>
                      <p className="helper">
                        Qualitative confidence: {record.output.confidence}. Citations are
                        references, not independent proof that an inference is correct.
                      </p>
                      {record.output.claims.map((claim, claimIndex) => (
                        <div className="model-claim" key={claimIndex}>
                          <p>{claim.text}</p>
                          <div className="evidence-refs">
                            {claim.evidence_event_ids.map((reference) => (
                              <button
                                key={reference}
                                type="button"
                                title={reference}
                                onClick={() => onEvidence(reference)}
                              >
                                <FileSearch size={12} />
                                {short(reference)}
                                <ArrowRight size={11} />
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                      <h3 className="mini-heading">Limitations</h3>
                      <ul className="plain-list">
                        {record.output.limitations.map((text) => (
                          <li key={text}>{text}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <RequestState request={record} />
                  )}
                </div>
              </details>
            ))
          )}
        </div>
      </div>
    </Panel>
  );
}

export function ImportedReportSummary({
  report,
  onObservation,
}: {
  report: ImportedReport;
  onObservation: (reference: string) => void;
}) {
  const provider = useAIStatus();
  const result = useQuery({
    queryKey: ["report-summary", report.id],
    queryFn: () => api<ReportSummaryHistory>(`/v1/integrations/hades/${report.id}/summary`),
    retry: false,
  });
  const summarize = useAction(
    () =>
      post<ReportSummary>(`/v1/integrations/hades/${report.id}/summary`, {
        expected_digest: report.digest,
      }),
    "Advisory metadata summary recorded. No scanner, policy or grant was activated.",
  );
  return (
    <section className="ai-report-summary">
      <h3>Advisory metadata summary</h3>
      <p className="helper">
        Only opaque local references, declared risk tiers and issue counts are sent. Raw scanner
        descriptions, tool names and code stay local. A heuristic report is not runtime exploit
        proof.
      </p>
      {provider.isError && (
        <ErrorState error={provider.error} retry={() => void provider.refetch()} />
      )}
      {result.isPending ? (
        <Loading label="Reading recorded report summaries..." />
      ) : result.isError ? (
        <ErrorState error={result.error} retry={() => void result.refetch()} />
      ) : (
        <>
          <div className="ai-form-actions">
            <span>
              {result.data.calls_used} / {result.data.report_call_budget} report requests used
            </span>
            <Button
              busy={summarize.isPending}
              disabled={
                !provider.data?.can_generate ||
                provider.data.calls_remaining === 0 ||
                result.data.calls_remaining === 0 ||
                report.observations.length === 0
              }
              onClick={() => summarize.mutate()}
            >
              <Sparkles size={14} />
              {provider.data?.mode === "fixture"
                ? "Generate fixture summary"
                : "Summarize metadata"}
            </Button>
          </div>
          {summarize.isError && (
            <p className="error-text" role="alert">
              {summarize.error.message}
            </p>
          )}
          <div className="ai-history">
            {result.data.items.map((record, index) => (
              <details key={record.id} className="ai-record" open={index === 0}>
                <summary>
                  <span>Summary / {time(record.started_at)}</span>
                  <Status value={record.state} />
                </summary>
                <div className="ai-record-body">
                  {record.output && record.state === "succeeded" ? (
                    <>
                      <Attribution value={record.output} />
                      <p className="ai-answer">{record.output.summary}</p>
                      <p className="helper">
                        {record.output.coverage.observations_supplied} /{" "}
                        {record.output.coverage.total_observations} observations supplied as
                        metadata only.
                      </p>
                      {record.output.claims.map((claim, claimIndex) => (
                        <div key={claimIndex} className="model-claim">
                          <p>{claim.text}</p>
                          <div className="evidence-refs">
                            {claim.observation_refs.map((reference) => (
                              <button
                                key={reference}
                                type="button"
                                onClick={() => onObservation(reference)}
                              >
                                {reference}
                                <ArrowRight size={11} />
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                      <h4>Review questions</h4>
                      <ul className="plain-list">
                        {record.output.review_questions.map((text) => (
                          <li key={text}>{text}</li>
                        ))}
                      </ul>
                      <h4>Limitations</h4>
                      <ul className="plain-list">
                        {record.output.limitations.map((text) => (
                          <li key={text}>{text}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <RequestState request={record} />
                  )}
                </div>
              </details>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
