import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  FileSearch,
  LoaderCircle,
  X,
} from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cloneElement, isValidElement, useId } from "react";
import type { HTMLAttributes } from "react";
import { Link } from "react-router-dom";
import type { EventRecord, Incident } from "./types";
import { errorMessage, useWorkspace } from "./state";
import { plainLabel, useLens } from "./experience";

export function Button({
  children,
  variant = "secondary",
  busy = false,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || busy}
      className={`button button-${variant} ${className}`}
      aria-busy={busy || undefined}
    >
      {busy && <LoaderCircle size={15} className="spin" aria-hidden="true" />}
      {children}
    </button>
  );
}
export function Badge({
  children,
  tone,
  dot = true,
}: {
  children: ReactNode;
  tone?: string;
  dot?: boolean;
}) {
  return (
    <span className={`badge badge-${tone ?? "neutral"}`}>
      {dot && <span className="badge-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
export function statusTone(value: string): string {
  if (
    [
      "high",
      "critical",
      "deny",
      "denied",
      "suspended",
      "rejected",
      "failure",
      "failed",
      "check-failed",
      "unknown",
    ].includes(value)
  )
    return "red";
  if (
    [
      "medium",
      "pending",
      "require_approval",
      "RESTRICTED",
      "DECOY_PENDING",
      "not-configured",
      "configured-unverified",
      "egress-disabled",
      "checking",
    ].includes(value)
  )
    return "amber";
  if (["DECOY", "simulated", "ACTIVE", "fixture", "report-imported"].includes(value))
    return "purple";
  if (
    [
      "allow",
      "success",
      "active",
      "approved",
      "consumed",
      "succeeded",
      "verified",
      "check-passed",
      "ready",
      "PRODUCTION",
    ].includes(value)
  )
    return "teal";
  return "neutral";
}
export function Status({ value }: { value: string }) {
  const { plain } = useLens();
  const label =
    (plain ? plainLabel(value) : undefined) ?? value.replaceAll("_", " ").replaceAll("-", " ");
  return <Badge tone={statusTone(value)}>{label}</Badge>;
}
export function ago(value: string | null) {
  if (!value) return "No observations";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
export function time(value: string) {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
export function short(value: string) {
  return value.length > 18 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}
export function PageHeading({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  const caseContext = eyebrow?.startsWith("HM-")
    ? eyebrow
        .replace("RECORDED LAB EXECUTION", "Recorded lab execution")
        .replace("DIRECT APPLICATION EVIDENCE", "Direct API evidence")
    : null;
  return (
    <header className="page-heading">
      <div>
        {caseContext && <p className="page-reference">{caseContext}</p>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="heading-actions">{actions}</div>}
    </header>
  );
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <header className="panel-heading">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
export function Loading({ label = "Loading recorded evidence..." }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={23} />
      <span>{label}</span>
      <div className="skeleton-lines">
        <i />
        <i />
        <i />
      </div>
    </div>
  );
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="empty-state error-state" role="alert">
      <CircleAlert size={27} />
      <h3>Unable to load this view</h3>
      <p>{errorMessage(error)}</p>
      {retry && <Button onClick={retry}>Try again</Button>}
    </div>
  );
}
export function Empty({
  title = "No records yet",
  description = "Recorded activity will appear here when the relevant workflow runs.",
  action,
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <FileSearch size={28} />
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide = false,
  drawer = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
  wide?: boolean;
  drawer?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className={`dialog-content ${wide ? "dialog-wide" : ""} ${drawer ? "dialog-drawer" : ""}`}
        >
          <div className="dialog-heading">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              <Dialog.Description>{description}</Dialog.Description>
            </div>
            <Dialog.Close className="icon-button" aria-label="Close dialog">
              <X size={19} />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Confirm({
  open,
  onOpenChange,
  title,
  description,
  consequence,
  onConfirm,
  busy,
  label = "Confirm action",
  danger = true,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  consequence: ReactNode;
  onConfirm: () => void;
  busy?: boolean;
  label?: string;
  danger?: boolean;
}) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} description={description}>
      <div className={`callout ${danger ? "callout-red" : "callout-amber"}`}>
        <CircleAlert size={19} />
        <div>{consequence}</div>
      </div>
      <div className="dialog-actions">
        <Button onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant={danger ? "danger" : "primary"} busy={busy} onClick={onConfirm}>
          {label}
        </Button>
      </div>
    </Modal>
  );
}
export function CodeBlock({ value, label }: { value: unknown; label?: string }) {
  return (
    <div className="code-block">
      {label && <div className="code-label">{label}</div>}
      <pre tabIndex={0}>{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}
export function Field({
  label,
  children,
  help,
}: {
  label: string;
  children: ReactNode;
  help?: string;
}) {
  const labelId = useId();
  const control =
    isValidElement<HTMLAttributes<HTMLElement>>(children) &&
    typeof children.type === "string" &&
    ["input", "select", "textarea"].includes(children.type)
      ? cloneElement(children, { "aria-labelledby": labelId })
      : children;
  return (
    <label className="field">
      <span id={labelId}>{label}</span>
      {control}
      {help && <small>{help}</small>}
    </label>
  );
}
export function KeyValue({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="key-value">
      <dt>{label}</dt>
      <dd className={mono ? "mono" : ""}>{children}</dd>
    </div>
  );
}
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: T; label: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="tabs" role="group" aria-label="View selection">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          aria-pressed={value === tab.value}
          onClick={() => onChange(tab.value)}
          className={value === tab.value ? "selected" : ""}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
export function Meter({
  value,
  max,
  label,
  tone = "teal",
}: {
  value: number;
  max: number;
  label: string;
  tone?: string;
}) {
  return (
    <div className="meter">
      <div>
        <span>{label}</span>
        <span className="tabular-numbers">
          {value.toLocaleString()} / {max.toLocaleString()}
        </span>
      </div>
      <div
        className="meter-track"
        role="progressbar"
        aria-label={label}
        aria-valuenow={value}
        aria-valuemax={max}
        aria-valuemin={0}
      >
        <span
          className={`meter-${tone}`}
          style={{ width: `${Math.min(100, Math.max(0, (value / max) * 100))}%` }}
        />
      </div>
    </div>
  );
}
export function Pagination({
  next,
  previous,
  pageNumber,
  loading,
}: {
  next?: () => void;
  previous?: () => void;
  pageNumber: number;
  loading?: boolean;
}) {
  return (
    <div className="pagination">
      <span>
        Page {pageNumber} <span className="muted">/ bounded results</span>
      </span>
      <div>
        <Button disabled={!previous || loading} onClick={previous}>
          <ChevronLeft size={15} />
          Previous
        </Button>
        <Button disabled={!next || loading} onClick={next}>
          Next
          <ChevronRight size={15} />
        </Button>
      </div>
    </div>
  );
}
export function IncidentTable({
  items,
  compact = false,
  onPreview,
}: {
  items: Incident[];
  compact?: boolean;
  onPreview?: (id: string) => void;
}) {
  if (!items.length)
    return (
      <Empty
        title="No incidents in this view"
        description="Normal activity and benign quotations do not create an incident by themselves."
      />
    );
  return (
    <div className="table-scroll">
      <table className={`incident-table ${compact ? "compact" : ""}`}>
        <thead>
          <tr>
            <th>Case / signal</th>
            <th>Severity</th>
            <th>Identity</th>
            <th>Response</th>
            <th>Updated</th>
            <th>
              <span className="sr-only">Open</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <Link className="case-link" to={`/incidents/${item.id}`}>
                  <span className="mono muted">{item.number}</span>
                  <strong>{item.title}</strong>
                </Link>
                <span className="table-meta">
                  {item.rules.join(" + ")} <span aria-hidden="true">&middot;</span>{" "}
                  {item.origin === "laboratory"
                    ? "Recorded lab execution"
                    : "Live application event"}
                </span>
              </td>
              <td data-label="Severity">
                <Status value={item.severity} />
              </td>
              <td data-label="Identity">
                <span className="mono small">{item.principal_id}</span>
                <span className="table-meta">{item.confidence} confidence</span>
              </td>
              <td data-label="Response">
                <Status value={item.route_mode ?? item.status} />
              </td>
              <td className="muted nowrap" data-label="Updated">
                {ago(item.updated_at)}
              </td>
              <td>
                {onPreview && (
                  <button
                    type="button"
                    className="preview-button"
                    aria-label={`Preview ${item.number}`}
                    onClick={() => onPreview(item.id)}
                  >
                    Preview
                  </button>
                )}
                <Link
                  className="icon-button"
                  aria-label={`Open ${item.number}`}
                  to={`/incidents/${item.id}`}
                >
                  <ArrowRight size={16} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function EvidenceDrawer({
  event,
  onClose,
}: {
  event: EventRecord | null;
  onClose: () => void;
}) {
  return (
    <Modal
      open={!!event}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Evidence detail"
      description="Authenticated metadata with untrusted content, rendered as inert text."
      drawer
    >
      {event && (
        <>
          <div className="row gap">
            <Status value={event.outcome} />
            <Badge tone={event.body.route_mode === "DECOY" ? "purple" : "neutral"}>
              {event.body.route_mode}
            </Badge>
            <Badge dot={false}>{event.origin}</Badge>
          </div>
          <dl className="detail-list">
            <KeyValue label="Event ID" mono>
              {event.id}
            </KeyValue>
            <KeyValue label="Type">{event.event_type}</KeyValue>
            <KeyValue label="Producer">{event.source}</KeyValue>
            <KeyValue label="Received (server)">{time(event.received_at)}</KeyValue>
            <KeyValue label="Observed (producer)">{time(event.occurred_at)}</KeyValue>
            <KeyValue label="Policy" mono>
              {event.body.attributes.policy_version ?? "Not attached"}
            </KeyValue>
          </dl>
          <CodeBlock label="Untrusted observation data" value={event.body.attributes} />
          <CodeBlock label="Immutable body digest" value={event.body_digest} />
          <p className="helper">
            Authenticated provenance does not make visitor text true or authoritative.
          </p>
        </>
      )}
    </Modal>
  );
}
export function Toast() {
  const { notice, dismiss } = useWorkspace();
  if (!notice) return null;
  return (
    <div
      className={`toast toast-${notice.kind}`}
      role={notice.kind === "error" ? "alert" : "status"}
    >
      {notice.kind === "error" ? <CircleAlert size={19} /> : <Check size={19} />}
      <span>{notice.message}</span>
      <button className="icon-button" aria-label="Dismiss notification" onClick={dismiss}>
        <X size={16} />
      </button>
    </div>
  );
}
