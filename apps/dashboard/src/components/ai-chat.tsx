import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, MessageSquarePlus, SendHorizontal, Sparkles, X } from "lucide-react";
import { api, post } from "../api";
import { Badge, ErrorState, Loading } from "../components";
import { useExperience } from "../experience";
import type { AIRequest, CaseAnswer, CaseDetail, WorkspaceAnswer } from "../types";
import { useAIStatus } from "./ai-workflows";

function ProviderBadge({ provider }: { provider: string }) {
  return (
    <Badge tone="purple" dot={false}>
      {provider === "fixture-investigator-v1"
        ? "Demo AI (fixture, not live Gemini)"
        : `AI · ${provider}`}
    </Badge>
  );
}

export function AIChatLauncher() {
  const { openChat, chatOpen } = useExperience();
  if (chatOpen) return null;
  return (
    <button type="button" className="ai-launcher" onClick={() => openChat()}>
      <Sparkles size={17} />
      Ask Mirage AI
    </button>
  );
}

export function AIChatPanel() {
  const { chat, chatOpen, closeChat, openChat } = useExperience();
  const client = useQueryClient();
  const status = useAIStatus();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sentFor = useRef<object | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const caseId = chat?.caseId;
  const detail = useQuery({
    queryKey: ["incident", caseId],
    queryFn: () => api<CaseDetail>(`/v1/incidents/${caseId}`),
    enabled: chatOpen && !!caseId,
  });
  const workspace = useQuery({
    queryKey: ["assistant-history"],
    queryFn: () => api<{ items: AIRequest<WorkspaceAnswer>[] }>("/v1/assistant"),
    enabled: chatOpen && !caseId,
  });
  async function send(question: string) {
    const text = question.trim();
    if (text.length < (caseId ? 8 : 3) || sending) return;
    setSending(true);
    setError(null);
    try {
      if (caseId) {
        const version = detail.data?.incident.version ?? chat?.caseVersion;
        await post<CaseAnswer>(`/v1/incidents/${caseId}/assistant`, {
          question: text,
          expected_version: version,
        });
        await client.invalidateQueries({ queryKey: ["incident", caseId] });
      } else {
        await post<WorkspaceAnswer>("/v1/assistant", { question: text });
        await client.invalidateQueries({ queryKey: ["assistant-history"] });
      }
      setDraft("");
      void client.invalidateQueries({ queryKey: ["ai-status"] });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The AI request failed");
      setDraft(text);
    } finally {
      setSending(false);
    }
  }
  useEffect(() => {
    if (!chatOpen || !chat || !chat.question) return;
    if (sentFor.current === chat) return;
    sentFor.current = chat;
    if (chat.autoSend && (!caseId || detail.data)) void send(chat.question);
    else setDraft(chat.question);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatOpen, chat, detail.data]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [detail.data, workspace.data, sending]);
  if (!chatOpen) return null;
  const caseItems = [...(detail.data?.assistant ?? [])].reverse();
  const workspaceItems = [...(workspace.data?.items ?? [])].reverse();
  return (
    <aside className="ai-chat-panel" aria-label="Ask Mirage AI">
      <header>
        <span className="ai-chat-title">
          <Sparkles size={18} />
          Ask Mirage AI
        </span>
        <span className="grow" />
        <button
          type="button"
          className="icon-button"
          aria-label="New workspace chat"
          title="New workspace chat"
          onClick={() => openChat()}
        >
          <MessageSquarePlus size={17} />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Close AI chat"
          onClick={closeChat}
        >
          <X size={17} />
        </button>
      </header>
      <div className="ai-chat-context">
        {caseId ? (
          <>
            <span>Asking about</span>
            <Link to={`/incidents/${caseId}`}>
              {chat?.caseNumber ?? detail.data?.incident.number ?? "this issue"}
              <ArrowUpRight size={12} />
            </Link>
          </>
        ) : (
          <span>Asking about the whole workspace</span>
        )}
        {status.data && <ProviderBadge provider={status.data.provider} />}
      </div>
      <div className="ai-chat-messages" aria-live="polite">
        {(caseId ? detail.isPending : workspace.isPending) ? (
          <Loading label="Loading the conversation..." />
        ) : (caseId ? detail.isError : workspace.isError) ? (
          <ErrorState error={caseId ? detail.error : workspace.error} />
        ) : (caseId ? caseItems.length : workspaceItems.length) === 0 && !sending ? (
          <div className="ai-chat-empty">
            <Sparkles size={26} />
            <strong>How can I help?</strong>
            <p>
              {caseId
                ? "Ask about this issue. Answers cite the recorded evidence."
                : "Ask about attacks, honeypot activity or what needs attention."}
            </p>
            <div className="ai-chips">
              {(caseId
                ? [
                    "What is the risk and impact?",
                    "Who should fix this?",
                    "Explain this in simple words",
                  ]
                : [
                    "What attacks happened today?",
                    "Which agents are in the honeypot?",
                    "What should I review first?",
                  ]
              ).map((text) => (
                <button key={text} type="button" onClick={() => void send(text)}>
                  <Sparkles size={13} />
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : caseId ? (
          caseItems.map((item) => (
            <div key={item.id} className="ai-chat-turn">
              <p className="ai-chat-question">{item.question}</p>
              {item.output && item.state === "succeeded" ? (
                <div className="ai-chat-answer">
                  <ProviderBadge provider={item.output.provider} />
                  <p>{item.output.answer}</p>
                  {item.output.claims.map((claim, index) => (
                    <p key={index} className="ai-chat-claim">
                      • {claim.text} <small>({claim.evidence_event_ids.length} cited events)</small>
                    </p>
                  ))}
                  <small className="ai-chat-limits">{item.output.limitations.join(" ")}</small>
                </div>
              ) : (
                <p className="error-text">{item.error_code ?? item.state}</p>
              )}
            </div>
          ))
        ) : (
          workspaceItems.map((item) => (
            <div key={item.id} className="ai-chat-turn">
              <p className="ai-chat-question">{item.question}</p>
              {item.output && item.state === "succeeded" ? (
                <div className="ai-chat-answer">
                  <ProviderBadge provider={item.output.provider} />
                  <p>{item.output.answer}</p>
                  {!!item.output.references.length && (
                    <div className="ai-chat-references">
                      {item.output.references.map((reference) => (
                        <Link key={reference.case_id} to={`/incidents/${reference.case_id}`}>
                          {reference.reason}
                          <ArrowUpRight size={12} />
                        </Link>
                      ))}
                    </div>
                  )}
                  <small className="ai-chat-limits">{item.output.limitations.join(" ")}</small>
                </div>
              ) : (
                <p className="error-text">{item.error_code ?? item.state}</p>
              )}
            </div>
          ))
        )}
        {sending && <Loading label="Mirage AI is thinking..." />}
        <div ref={endRef} />
      </div>
      {error && (
        <p className="error-text ai-chat-error" role="alert">
          {error}
        </p>
      )}
      <form
        className="ai-chat-input"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <label className="sr-only" htmlFor="ai-chat-input">
          Ask Mirage AI
        </label>
        <input
          id="ai-chat-input"
          value={draft}
          maxLength={1000}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask anything..."
          disabled={sending}
        />
        <button
          type="submit"
          aria-label="Send question"
          disabled={sending || draft.trim().length < 3}
        >
          <SendHorizontal size={16} />
        </button>
      </form>
      <footer>
        <Sparkles size={12} /> AI generated · advisory only · cannot change access
      </footer>
    </aside>
  );
}
