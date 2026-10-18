import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Bot,
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Download,
  Ghost,
  MessageSquare,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { api, download, post } from "../api";
import { Badge, Button, ErrorState, Loading, Status, Tabs, ago, time } from "../components";
import { useExperience, useLens, LensToggle, plainRules } from "../experience";
import { useAction } from "../state";
import type { CaseDetail, EventRecord } from "../types";
import { AttackChain, AttackPathGraph, AttackStory, useAttackPath } from "./attack-path";

const QUESTIONS = [
  "What is the risk and impact?",
  "Who should fix this?",
  "Are there any related issues?",
];

export function SeverityPill({ value }: { value: string }) {
  return (
    <span className={`severity-pill sev-${value}`}>{value[0].toUpperCase() + value.slice(1)}</span>
  );
}

export function IssueDrawer({
  caseId,
  onClose,
  onEvidence,
}: {
  caseId: string | null;
  onClose: () => void;
  onEvidence: (event: EventRecord) => void;
}) {
  return (
    <Dialog.Root open={!!caseId} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay issue-overlay" />
        <Dialog.Content className="issue-drawer">
          <Dialog.Title className="sr-only">Issue details</Dialog.Title>
          <Dialog.Description className="sr-only">
            Attack path, plain and technical explanation, and AI analysis for this issue.
          </Dialog.Description>
          {caseId && <IssuePanel caseId={caseId} onClose={onClose} onEvidence={onEvidence} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function IssuePanel({
  caseId,
  onClose,
  onEvidence,
  embedded = false,
}: {
  caseId: string;
  onClose?: () => void;
  onEvidence: (event: EventRecord) => void;
  embedded?: boolean;
}) {
  const { plain } = useLens();
  const { openChat } = useExperience();
  const [tab, setTab] = useState("overview");
  const [explanationOpen, setExplanationOpen] = useState(true);
  const detail = useQuery({
    queryKey: ["incident", caseId],
    queryFn: () => api<CaseDetail>(`/v1/incidents/${caseId}`),
  });
  const path = useAttackPath(caseId);
  const investigate = useAction(
    () => post(`/v1/incidents/${caseId}/investigate`),
    "AI analysis recorded. It is advice only; access did not change.",
  );
  const exportCase = useAction(
    () => download(`/v1/incidents/${caseId}/export?format=html`, `mirage-issue-${caseId}.html`),
    "Issue report exported.",
  );
  if (detail.isPending || path.isPending)
    return (
      <section className="issue-panel">
        <Loading label="Opening the issue..." />
      </section>
    );
  if (detail.isError)
    return (
      <section className="issue-panel">
        <ErrorState error={detail.error} retry={() => void detail.refetch()} />
      </section>
    );
  if (path.isError)
    return (
      <section className="issue-panel">
        <ErrorState error={path.error} retry={() => void path.refetch()} />
      </section>
    );
  const { incident, session, events, investigation } = detail.data;
  const story = path.data;
  const findEvent = (id: string) => {
    const event = events.find((item) => item.id === id);
    if (event) onEvidence(event);
  };
  const ask = (question?: string) =>
    openChat({
      caseId: incident.id,
      caseNumber: incident.number,
      caseVersion: incident.version,
      question,
      autoSend: !!question,
    });
  return (
    <section
      className={`issue-panel ${embedded ? "embedded" : ""}`}
      aria-label={`Issue ${incident.number}`}
    >
      <header className="issue-header">
        <span className={`issue-icon sev-${incident.severity}`}>
          {story.verdict.in_honeypot ? <Ghost size={22} /> : <ShieldAlert size={22} />}
        </span>
        <div className="issue-heading">
          <h2>{plain ? (story.rules[0]?.plain ?? incident.title) : incident.title}</h2>
          <p>
            Issue · {incident.number} · {plain ? "Opened" : "created"} {ago(incident.created_at)}
          </p>
        </div>
        <LensToggle compact />
        {onClose && (
          <button type="button" className="icon-button" aria-label="Close issue" onClick={onClose}>
            <X size={18} />
          </button>
        )}
      </header>
      <div className="issue-actions">
        <Button onClick={() => ask()}>
          <MessageSquare size={15} />
          Ask AI
        </Button>
        <Button busy={exportCase.isPending} onClick={() => exportCase.mutate()}>
          <Download size={15} />
          Export report
        </Button>
        {!embedded && (
          <Link className="button button-secondary" to={`/incidents/${incident.id}`}>
            Full investigation
            <ArrowUpRight size={14} />
          </Link>
        )}
      </div>
      {story.verdict.contained && (
        <div
          className={`issue-banner ${story.verdict.in_honeypot ? "banner-honeypot" : "banner-blocked"}`}
        >
          <Ghost size={16} />
          {plain
            ? story.verdict.in_honeypot
              ? "Detected by behaviour and moved into the honeypot (fake environment)."
              : "Detected and blocked. Its access was limited."
            : `Session ${story.verdict.route_technical}; rules ${story.rules.map((rule) => rule.id).join(", ")}.`}
          {!story.verdict.real_data_touched && (
            <span className="banner-safe">
              {plain ? "No real data touched" : "0 linked backend executions"}
            </span>
          )}
        </div>
      )}
      <div className="issue-body-grid">
        <div className="issue-main">
          <p className="issue-description">
            {plain ? story.headline_plain : story.headline_technical}
          </p>
          <AttackChain path={story} />
          <div className="ai-chips">
            {QUESTIONS.map((question) => (
              <button key={question} type="button" onClick={() => ask(question)}>
                <Sparkles size={14} />
                {question}
              </button>
            ))}
          </div>
          <dl className="issue-facts">
            <div>
              <dt>{plain ? "Who" : "Principal"}</dt>
              <dd>
                {plain
                  ? story.verdict.external
                    ? "Outside AI agent"
                    : "Internal AI agent"
                  : incident.principal_id}
              </dd>
            </div>
            <div>
              <dt>{plain ? "Where" : "Application"}</dt>
              <dd>Procurement app</dd>
            </div>
            <div>
              <dt>Severity</dt>
              <dd>
                <SeverityPill value={incident.severity} />
              </dd>
            </div>
            <div>
              <dt>{plain ? "What we noticed" : "Detection rules"}</dt>
              <dd>
                {story.rules.map((rule) => (
                  <Badge key={rule.id} tone="blue" dot={false}>
                    {plain ? (plainRules[rule.id] ?? rule.plain) : rule.id}
                  </Badge>
                ))}
              </dd>
            </div>
            <div>
              <dt>{plain ? "Right now" : "Route state"}</dt>
              <dd>
                <Status value={session.route_mode} />
              </dd>
            </div>
            <div>
              <dt>{plain ? "Blocked attempts" : "Denied decisions"}</dt>
              <dd>{story.verdict.blocked}</dd>
            </div>
          </dl>
        </div>
        <aside className="issue-side">
          <dl>
            <div>
              <dt>Status</dt>
              <dd>
                <Status value={incident.status} />
              </dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{time(incident.created_at)}</dd>
            </div>
            <div>
              <dt>Last updated</dt>
              <dd>{time(incident.updated_at)}</dd>
            </div>
            <div>
              <dt>{plain ? "Honeypot" : "Decoy"}</dt>
              <dd>{story.verdict.in_honeypot ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt>{plain ? "Real data touched" : "Backend executions"}</dt>
              <dd>{story.verdict.real_data_touched ? "Allowed reads only" : "No"}</dd>
            </div>
          </dl>
        </aside>
      </div>
      <div className="ai-agent-card">
        <span className="ai-agent-icon">
          <Bot size={22} />
        </span>
        <div>
          <strong>Investigate with the AI agent</strong>
          <p>
            {plain
              ? "AI reads the recorded evidence and explains it in plain words. It can only advise."
              : "Bounded advisory investigation; schema-validated, evidence-cited, no tools or routing authority."}
          </p>
          <div className="row wrap">
            <Button
              busy={investigate.isPending}
              disabled={detail.data.model_budget.remaining === 0}
              onClick={() => investigate.mutate()}
            >
              <BrainCircuit size={15} />
              {investigation ? "Run AI analysis again" : "Run AI analysis"}
            </Button>
            <small>
              <Sparkles size={12} /> {detail.data.model_budget.remaining} AI runs left for this
              issue
            </small>
          </div>
        </div>
      </div>
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "overview", label: "Overview" },
          { value: "timeline", label: plain ? "What happened" : "Timeline" },
          { value: "ai", label: "AI analysis" },
          { value: "evidence", label: plain ? "Raw evidence" : "Events" },
        ]}
      />
      {tab === "overview" ? (
        <>
          <div className="explanation-card">
            <button
              type="button"
              className="explanation-toggle"
              aria-expanded={explanationOpen}
              onClick={() => setExplanationOpen((value) => !value)}
            >
              {explanationOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              Attack path explanation
              <span className="explanation-source">
                <Sparkles size={12} />
                {investigation ? "AI generated" : "Built from recorded evidence"}
              </span>
            </button>
            {explanationOpen && (
              <div className="explanation-body">
                <p>
                  <strong>{plain ? "How it started: " : "Initial access: "}</strong>
                  {
                    story.nodes.find((node) => node.id === "source")?.[
                      plain ? "plain" : "technical"
                    ]
                  }
                </p>
                <p>
                  <strong>{plain ? "What it tried: " : "Execution: "}</strong>
                  {story.nodes.find((node) => node.id === "guardrail")?.[
                    plain ? "plain" : "technical"
                  ] ??
                    (plain
                      ? "Its requests were checked by our rules."
                      : "No deny decisions recorded.")}
                </p>
                <p>
                  <strong>{plain ? "What we did: " : "Response: "}</strong>
                  {
                    (story.nodes.find((node) => node.id === "honeypot") ??
                      story.nodes.find((node) => node.id === "limit") ??
                      story.nodes.find((node) => node.id === "detection"))?.[
                      plain ? "plain" : "technical"
                    ]
                  }
                </p>
                <p>
                  <strong>{plain ? "Result: " : "Impact: "}</strong>
                  {story.nodes.find((node) => node.id === "data")?.[plain ? "plain" : "technical"]}
                </p>
                {investigation && (
                  <p>
                    <strong>AI: </strong>
                    {investigation.summary}
                  </p>
                )}
                <Button
                  variant="ghost"
                  onClick={() => ask("Explain this attack path in simple words")}
                >
                  <Sparkles size={14} />
                  Continue in chat
                </Button>
              </div>
            )}
          </div>
          <div className="graph-card">
            <div className="graph-card-heading">
              <h3>Attack path visualization</h3>
              <span>
                {plain ? "Click any step to see details" : "Nodes link to recorded event IDs"}
              </span>
            </div>
            <AttackPathGraph path={story} onEvidence={findEvent} />
          </div>
        </>
      ) : tab === "timeline" ? (
        <AttackStory path={story} />
      ) : tab === "ai" ? (
        <div className="explanation-body">
          {investigation ? (
            <>
              <Badge tone="purple" dot={false}>
                {investigation.provider === "fixture-investigator-v1"
                  ? "Demo AI output (fixture, not live Gemini)"
                  : `AI · ${investigation.model ?? investigation.provider}`}
              </Badge>
              <p>{investigation.summary}</p>
              {investigation.claims.map((claim, index) => (
                <div className="model-claim" key={index}>
                  <p>{claim.text}</p>
                  <div className="evidence-refs">
                    {claim.evidence_event_ids.map((id) => (
                      <button key={id} type="button" onClick={() => findEvent(id)} title={id}>
                        {id.slice(0, 8)}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <p className="helper">
                Suggested next step: {investigation.recommended_response.replaceAll("_", " ")}.
                Advice only; it does not change access.
              </p>
            </>
          ) : (
            <p className="helper">No AI analysis yet. Use “Run AI analysis” above.</p>
          )}
        </div>
      ) : (
        <div className="issue-events">
          {events.slice(-40).map((event) => (
            <button type="button" key={event.id} onClick={() => onEvidence(event)}>
              <span>{event.body.attributes.tool ?? event.event_type}</span>
              <Status value={event.outcome} />
              <small>{time(event.received_at)}</small>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
