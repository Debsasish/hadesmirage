import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  CircleAlert,
  Database,
  Fingerprint,
  Moon,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { api } from "../api";
import { Badge, CodeBlock, ErrorState, KeyValue, Loading, PageHeading, Panel } from "../components";
import { useAction, useMe, useWorkspace } from "../state";
import type { Configuration } from "../types";
import { AIProviderPanel } from "../components/ai-workflows";

export function SettingsPage() {
  const me = useMe();
  const { theme, setTheme, translucent, setTranslucent } = useWorkspace();
  const result = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<Configuration>("/v1/settings"),
  });
  const update = useAction(
    (enabled: boolean) =>
      api("/v1/settings", {
        method: "PATCH",
        body: JSON.stringify({ engagements_enabled: enabled }),
      }),
    "Engagement policy updated; application authorization remains active.",
  );
  if (result.isPending)
    return <Loading label="Loading the active profile and versioned configuration..." />;
  if (result.isError) return <ErrorState error={result.error} />;
  const data = result.data;
  const admin = me.data?.principal.roles.includes("security_admin");
  return (
    <div className="page">
      <PageHeading
        eyebrow="WORKSPACE / HONEST DEPLOYMENT STATE"
        title="Settings"
        description="Active profile, safe operational controls, source versions, and known gaps."
        actions={<Badge tone="teal">{data.profile} / native only</Badge>}
      />
      <div className="settings-grid">
        <Panel title="Environment & authority" action={<Fingerprint size={18} />}>
          <div className="panel-body">
            <dl className="detail-list">
              <KeyValue label="Workspace">{me.data?.tenant.name}</KeyValue>
              <KeyValue label="Deployment profile">{data.profile}</KeyValue>
              <KeyValue label="Authoritative store">
                <span className="row">
                  <Database size={14} />
                  {data.storage === "sqlite"
                    ? "SQLite / WAL / serialized dispatch fence"
                    : data.storage}
                </span>
              </KeyValue>
              <KeyValue label="Identity provider">Local generated fixture credentials</KeyValue>
              <KeyValue label="Active policy" mono>
                {data.active_policy_version}
              </KeyValue>
              <KeyValue label="Retention">
                {data.retention_event_days} days / unreferenced redacted metadata
              </KeyValue>
            </dl>
            <div className="callout callout-amber">
              <CircleAlert size={17} />
              <div>
                Native fixture login is loopback-only. Do not expose this profile on the Internet or
                use it for production records.
              </div>
            </div>
          </div>
        </Panel>
        <Panel title="Appearance" subtitle="A complete dark and light visual system">
          <div className="panel-body">
            <div className="theme-choices">
              <button
                aria-pressed={theme === "dark"}
                className={theme === "dark" ? "selected" : ""}
                onClick={() => setTheme("dark")}
              >
                <div className="theme-preview preview-dark">
                  <i />
                  <span />
                  <span />
                </div>
                <span>
                  <Moon size={15} />
                  Dark
                </span>
              </button>
              <button
                aria-pressed={theme === "light"}
                className={theme === "light" ? "selected" : ""}
                onClick={() => setTheme("light")}
              >
                <div className="theme-preview preview-light">
                  <i />
                  <span />
                  <span />
                </div>
                <span>
                  <Sun size={15} />
                  Light
                </span>
              </button>
            </div>
            <div className="settings-toggle-row transparency-preference">
              <div>
                <h3>Translucent surfaces</h3>
                <p id="transparency-help">
                  Optional toolbar material. Evidence and data surfaces stay opaque for clarity.
                  Saved only in this browser.
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-label="Translucent surfaces"
                aria-describedby="transparency-help"
                aria-checked={translucent}
                className={`switch ${translucent ? "on" : ""}`}
                onClick={() => setTranslucent(!translucent)}
              >
                <span />
              </button>
            </div>
            <p className="helper">
              Saved in this browser. Focus indicators, non-colour status labels, and reduced-motion
              support are enabled in both themes.
            </p>
          </div>
        </Panel>
        <Panel title="Engagement policy" action={<SlidersHorizontal size={17} />}>
          <div className="panel-body">
            <div className="settings-toggle-row">
              <div>
                <h3>New eligible engagements</h3>
                <p>Requires deterministic corroboration and a ready verified template.</p>
              </div>
              <button
                role="switch"
                aria-label="Enable new eligible engagements"
                aria-checked={data.engagements_enabled}
                disabled={!admin || update.isPending}
                className={`switch ${data.engagements_enabled ? "on" : ""}`}
                onClick={() => update.mutate(!data.engagements_enabled)}
              >
                <span />
              </button>
            </div>
            <dl className="compact-details">
              <KeyValue label="Session TTL">{data.session_ttl_seconds / 60} minutes</KeyValue>
              <KeyValue label="Requests per engagement">{data.decoy_request_budget}</KeyValue>
              <KeyValue label="Concurrent engagement cap">{data.max_engagements}</KeyValue>
              <KeyValue label="Investigation / wording calls">
                {data.model_calls} / {data.model_call_budget}
              </KeyValue>
              <KeyValue label="Template version">{data.template_version}</KeyValue>
            </dl>
            <Link className="text-link" to="/deception">
              Termination & kill switch
              <ArrowUpRight size={13} />
            </Link>
            <p className="helper">
              Disabling new engagement does not terminate existing decoys or disable authorization.
              Use the explicit kill switch to stop active sessions.
            </p>
          </div>
        </Panel>
        <AIProviderPanel />
      </div>
      <Panel
        title="Known boundaries & release gaps"
        subtitle="These remain explicit even when the interface and local workflows work."
        action={<Badge tone="amber">Not production-ready</Badge>}
      >
        <div className="gap-list">
          {data.gaps.map((gap) => (
            <div key={gap}>
              <CircleAlert size={16} />
              <p>{gap}</p>
            </div>
          ))}
        </div>
      </Panel>
      <div className="settings-grid">
        <Panel title="Configuration fingerprint">
          <div className="panel-body">
            <p className="helper">
              Public effective settings, template and policy version. No connection strings, access
              codes, or provider credentials are included.
            </p>
            <CodeBlock
              label="SHA-256 / effective public configuration"
              value={data.config_digest}
            />
            <CodeBlock label="Compiled synthetic template SHA-256" value={data.template_sha256} />
          </div>
        </Panel>
        <Panel title="Before an enterprise pilot">
          <div className="panel-body">
            <ul className="plain-list">
              <li>
                Approved SSO, workload identity, credential rotation, and separation of duties.
              </li>
              <li>Native gateway and actual bypass/revocation acceptance evidence.</li>
              <li>PostgreSQL and multi-instance load/recovery validation.</li>
              <li>
                Cloud IAM/origin/isolation checks, privacy approval, and protected audit retention.
              </li>
              <li>Independent review of the explicitly scoped deployment.</li>
            </ul>
            <Link className="text-link" to="/architecture">
              Inspect the implemented architecture
              <ArrowUpRight size={13} />
            </Link>
          </div>
        </Panel>
      </div>
    </div>
  );
}
