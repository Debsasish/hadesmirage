export type Role = "analyst" | "security_admin" | "approver" | "workload" | "external";
export type RouteMode = "PRODUCTION" | "RESTRICTED" | "DECOY_PENDING" | "DECOY" | "TERMINATED";
export type Tool =
  | "supplier.lookup"
  | "invoice.compare"
  | "payment.change_request"
  | "customer.export"
  | "infrastructure.delete";
export type Action = "read" | "analyze" | "propose_change" | "export" | "delete";
export type Origin = "all" | "live" | "laboratory";

export interface GrantScope {
  tool: Tool;
  action: Action;
  resources: string[];
}
export interface Principal {
  tenant_id: string;
  id: string;
  name: string;
  kind: string;
  roles: Role[];
  status: string;
  scopes: GrantScope[];
  parent_id: string | null;
  root_id: string;
  depth: number;
  expires_at: string;
  identity_epoch: number;
  owner: string;
  created_at: string;
}
export interface Me {
  principal: Principal;
  csrf: string | null;
  profile: string;
  tenant: { id: string; name: string };
  model_provider: string;
  local_fixture_identity: boolean;
}
export interface EventRecord {
  tenant_id: string;
  id: string;
  sequence: number;
  session_id: string;
  source: string;
  event_type: string;
  outcome: string;
  received_at: string;
  occurred_at: string;
  body_digest: string;
  trusted: boolean;
  origin: string;
  body: {
    schema_version: string;
    event_id: string;
    session_id: string;
    principal_id: string;
    route_mode: RouteMode;
    outcome: string;
    attributes: {
      tool?: string;
      action?: string;
      resource?: string;
      policy_version?: string;
      reason_code?: string;
      snippet?: string;
      destination?: string;
    };
  };
}
export interface Incident {
  tenant_id: string;
  id: string;
  number: string;
  session_id: string;
  principal_id: string;
  title: string;
  summary: string;
  severity: string;
  confidence: string;
  status: string;
  version: number;
  rules: string[];
  source: string;
  origin: string;
  investigation: Investigation | null;
  model_error: string | null;
  model_calls: number;
  created_at: string;
  updated_at: string;
  route_mode?: RouteMode;
  route_version?: number;
}
export interface Session {
  tenant_id: string;
  id: string;
  principal_id: string;
  caller_class: string;
  route_mode: RouteMode;
  route_version: number;
  decoy_id: string | null;
  origin: string;
  created_at: string;
  expires_at: string;
  history: { mode: RouteMode; version: number; at: string; reason: string }[];
}
export interface AIGeneration {
  provider: string;
  model?: string | null;
  generated_at: string;
  tokens: number | null;
  request_id?: string;
  context_digest?: string;
  ai_config_digest?: string;
  duration_ms?: number;
  advisory_only?: boolean;
}
export interface Investigation extends AIGeneration {
  case_id: string;
  case_version: number;
  summary: string;
  confidence: string;
  claims: { text: string; evidence_event_ids: string[] }[];
  alternative_explanations: string[];
  recommended_response: string;
}
export interface CaseAnswer extends AIGeneration {
  case_id: string;
  case_version: number;
  answer: string;
  confidence: string;
  claims: { text: string; evidence_event_ids: string[] }[];
  limitations: string[];
  coverage: { events_supplied: number; event_limit: number; conversation_memory: false };
}
export interface ReportSummary extends AIGeneration {
  report_id: string;
  report_digest: string;
  summary: string;
  claims: { text: string; observation_refs: string[] }[];
  review_questions: string[];
  limitations: string[];
  coverage: {
    observations_supplied: number;
    total_observations: number;
    raw_text_sent: false;
    tool_names_sent: false;
  };
}
export interface AIRequest<T> {
  id: string;
  purpose: string;
  resource_version: number | null;
  provider: string;
  state: "pending" | "succeeded" | "failed" | "unknown";
  question: string | null;
  output: T | null;
  error_code: string | null;
  tokens: number | null;
  started_at: string;
  deadline_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}
export interface AIProviderCheck extends AIGeneration {
  status: "mirage-provider-check-v1";
  live: boolean;
  scope: string;
}
export interface AIProviderStatus {
  project: string | null;
  api_key_configured: boolean;
  credential: "api-key" | "workload-identity" | "none";
  endpoint: string;
  auto_triage: boolean;
  settings_version: number;
  settings_updated_by: string | null;
  settings_updated_at: string | null;
  settings_source: "portal" | "environment";
  provider: string;
  mode: "fixture" | "gemini" | "unavailable";
  model: string | null;
  region: string;
  project_configured: boolean;
  egress_approved: boolean;
  policy_version: string;
  timeout_seconds: number;
  input_bytes: number;
  max_output_tokens: number;
  case_call_budget: number;
  tenant_call_budget: number;
  max_pending: number;
  decoy_wording_enabled: boolean;
  advisory_only: true;
  tools_enabled: false;
  config_digest: string;
  state: string;
  can_generate: boolean;
  live_check_passed: boolean;
  last_check: AIRequest<AIProviderCheck> | null;
  call_reservations_used: number;
  calls_remaining: number;
  reported_tokens: number;
  requests_without_reported_usage: number;
  pending_requests: number;
  credentials: string;
  check_scope: string;
}
export interface ReportSummaryHistory {
  items: AIRequest<ReportSummary>[];
  report_call_budget: number;
  calls_used: number;
  calls_remaining: number;
}
export interface Note {
  id: string;
  text: string;
  actor_id: string;
  created_at: string;
}
export interface Rule {
  id: string;
  name: string;
  threshold: string;
  response: string;
  severity: string;
  version?: string;
}
export interface BackendEvidence {
  production_reads: number;
  production_mutations: number;
  evidence_source: string;
  effects: { execution_id: string; tool: string; mutated: number; created_at: string }[];
}
export interface CaseDetail {
  incident: Incident;
  events: EventRecord[];
  session: Session;
  notes: Note[];
  rules: Rule[];
  backend_outcomes: { id: string; state: string; decision: Record<string, unknown> }[];
  backend_evidence: BackendEvidence;
  investigation: Investigation | null;
  assistant: AIRequest<CaseAnswer>[];
  model_budget: { limit: number; used: number; remaining: number };
  application: string;
}
export interface Attestation {
  verified: boolean;
  verified_at: string;
  expires_at: string;
  module_sha256: string;
  runtime: string;
  memory_limit_bytes: number;
  fuel_per_request: number;
  host_imports: number;
  probes: { target: string; denied: boolean; method: string; evidence: string }[];
  scope: string;
}
export interface TrendBucket {
  label: string;
  authorized: number;
  denied: number;
  deception: number;
}
export interface Overview {
  profile: string;
  version: string;
  data_scope: Origin;
  protected_applications: number;
  registered_agents: number;
  authorized_operations: number;
  denied_operations: number;
  open_incidents: number;
  incident_severities: Record<string, number>;
  active_decoys: number;
  pending_approvals: number;
  decoy_failures: number;
  event_count: number;
  event_count_capped: boolean;
  outbox_pending: number;
  last_event_at: string | null;
  recent_events: EventRecord[];
  recent_incidents: Incident[];
  trend: TrendBucket[];
  policy_version: string;
  policy_digest: string;
  model: { provider: string; calls: number; tokens: number; budget: number; advisory: boolean };
  engagements_enabled: boolean;
  isolation: Attestation;
  backend_ready: boolean;
  gateway_state: string;
  hours: number;
}
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}
export interface Invocation {
  tool: Tool;
  action: Action;
  resource: string;
  arguments: { supplier_id?: string; invoice_id?: string; proposed_account_ref?: string };
  session_id: string;
  approval_id?: string;
}
export interface PolicyRule {
  id: string;
  effect: "allow" | "deny";
  principal_ids: string[];
  tool: string;
  actions: string[];
  resource_prefix: string;
  approval_required: boolean;
}
export interface PolicyDocument {
  schema_version: "1.0";
  policy_id: string;
  version: string;
  default_effect: "deny";
  rules: PolicyRule[];
}
export interface PolicyVersion {
  id: string;
  version: string;
  digest: string;
  status: string;
  document: PolicyDocument;
  created_by: string;
  reviewed_by: string | null;
  tested: boolean;
  created_at: string;
  fixture_results?: { tool: string; expected: string; actual: string; passed: boolean }[];
}
export interface Approval {
  id: string;
  requester_id: string;
  principal_id: string;
  session_id: string;
  digest: string;
  policy_version: string;
  invocation: Invocation;
  status: string;
  approver_id: string | null;
  expires_at: string;
  created_at: string;
}
export interface Decoy {
  id: string;
  session_id: string;
  template_id: string;
  template_version: string;
  state: string;
  synthetic_state: Record<string, number>;
  requests: number;
  model_tokens: number;
  expires_at: string;
  created_at: string;
  attestation: Attestation;
  cleanup_state: string;
}
export interface DeceptionData {
  items: Decoy[];
  engagements_enabled: boolean;
  templates: {
    id: string;
    version: string;
    name: string;
    runtime: string;
    ready: boolean;
    isolation: Attestation;
    description: string;
    tools: string[];
  }[];
  budgets: {
    requests: number;
    ttl_seconds: number;
    concurrent: number;
    model_tokens_per_session: number;
    wording_budget_units_per_session: number;
    wording_budget_definition: string;
    model_wording_enabled: boolean;
  };
}
export interface Integration {
  id: string;
  name: string;
  category: string;
  state: string;
  active_connection: boolean;
  version: string;
  license: string;
  last_success: string | null;
  last_error: string | null;
  capabilities: string[];
  limitations: string[];
}
export interface ImportedReport {
  id: string;
  source: string;
  version: string;
  digest: string;
  created_at: string;
  observations: {
    name: string;
    risk_tier: string;
    issues: string[];
    evidence_kind: string;
    runtime_verified: boolean;
    authority: string;
  }[];
}
export interface IntegrationsData {
  items: Integration[];
  imports: ImportedReport[];
  provenance: Record<string, unknown>;
  ai: AIProviderStatus;
}
export interface AuditRecord {
  id: string;
  sequence: number;
  actor_id: string;
  action: string;
  object_id: string;
  details: Record<string, unknown>;
  created_at: string;
  previous_digest: string;
  integrity_digest: string;
}
export interface Configuration {
  profile: string;
  storage: string;
  local_fixture_login: boolean;
  model_provider: string;
  gemini_model: string | null;
  gemini_region: string;
  active_policy_version: string;
  engagements_enabled: boolean;
  session_ttl_seconds: number;
  decoy_request_budget: number;
  max_engagements: number;
  model_call_budget: number;
  model_case_call_budget: number;
  model_egress_approved: boolean;
  ai_config_digest: string;
  model_calls: number;
  template_version: string;
  template_sha256: string;
  retention_event_days: number;
  config_digest: string;
  provenance: Record<string, unknown>;
  gaps: string[];
  ai: AIProviderStatus;
}
export interface TopologyNode {
  id: string;
  name: string;
  plane: string;
  osi: string;
  status: string;
  role: string;
  identity: string;
  x: number;
  y: number;
}
export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  protocol: string;
  state: string;
  detail: string;
}
export interface Topology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  profile: string;
  recorded_events: number;
  osi_note: string;
}
export interface MapFact {
  plain: string;
  technical: string;
  value: number | string | null;
  tone: string;
}
export interface MapBreakdown {
  key: string;
  plain: string;
  technical: string;
  count: number;
}
export interface MapNode {
  id: string;
  tone: string;
  label_plain: string;
  label_technical: string;
  about_plain: string;
  about_technical: string;
  value: number | null;
  unit: string;
  facts: MapFact[];
  breakdown: MapBreakdown[];
}
export interface MapEdge {
  id: string;
  source: string;
  target: string;
  tone: string;
  unit: string;
  plain: string;
  technical: string;
  count: number;
}
export interface MapAttacker {
  session_id: string;
  principal_id: string;
  principal_name: string;
  caller_class: string;
  origin: string;
  requests: number;
  allowed: number;
  blocked: number;
  simulated: number;
  first_seen: string | null;
  last_seen: string | null;
  route_mode: string;
  verdict_plain: string;
  top_tool: string | null;
  top_tool_plain: string | null;
  incident: {
    id: string;
    number: string;
    title: string;
    severity: string;
    status: string;
    rules: string[];
    rule_plain: string;
    ai_reviewed: boolean;
  } | null;
  path: string[];
  edges: string[];
}
export interface MapFeedItem {
  id: string;
  at: string;
  session_id: string;
  caller_class: string;
  tone: string;
  plain: string;
  technical: string;
}
export interface LiveAttackMap {
  generated_at: string;
  hours: number;
  origin: string;
  profile: string;
  capped: boolean;
  totals: {
    requests: number;
    allowed: number;
    approval: number;
    held_for_approval: number;
    approval_requests: number;
    blocked: number;
    simulated: number;
    agents: number;
    external_agents: number;
    sessions: number;
    flagged: number;
    flagged_external: number;
    limited: number;
    honeypot: number;
    active_honeypot: number;
    disconnected: number;
    ai_reviewed: number;
  };
  ledger: {
    available: boolean;
    actions: number | null;
    reads: number | null;
    changes: number | null;
    after_containment: number | null;
    flagged_before_containment: number | null;
    outside_view: number | null;
    source: string;
  };
  nodes: MapNode[];
  edges: MapEdge[];
  attackers: MapAttacker[];
  feed: MapFeedItem[];
  gateway: { state: string; plain: string; technical: string };
}
export interface Scenario {
  id: string;
  title: string;
  description: string;
  test_ids: string[];
}
export interface ScenarioResult {
  status: string;
  scenario: string;
  profile: string;
  origin: string;
  session: Session;
  outcomes: { http_status: number; response: Record<string, unknown>; tool?: string }[];
  approval: Approval | null;
  incident_id: string | null;
  backend_effect_delta: { production_reads: number; production_mutations: number };
  evidence_source: string;
  completed_at: string;
  fault_injection: boolean;
}

export interface AttackNode {
  id: string;
  kind: string;
  column: number;
  row: number;
  label_plain: string;
  label_technical: string;
  sub_plain: string;
  sub_technical: string;
  plain: string;
  technical: string;
  status: string;
  badges: string[];
  event_ids: string[];
}
export interface AttackEdge {
  id: string;
  source: string;
  target: string;
  plain: string;
  technical: string;
  kind: string;
}
export interface AttackStep {
  plain: string;
  technical: string;
  kind: string;
  event_ids: string[];
  count: number;
  at?: string;
}
export interface AttackPath {
  case_id: string;
  number: string;
  headline_plain: string;
  headline_technical: string;
  verdict: {
    external: boolean;
    blocked: number;
    allowed: number;
    contained: boolean;
    in_honeypot: boolean;
    real_data_touched: boolean;
    route_plain: string;
    route_technical: string;
  };
  rules: { id: string; plain: string }[];
  nodes: AttackNode[];
  edges: AttackEdge[];
  steps: AttackStep[];
  source: string;
}
export interface BoardData {
  generated_at: string;
  severity: {
    level: "critical" | "high" | "medium" | "low";
    open: number;
    opened_7d: number;
    change_percent: number | null;
    average_age_days: number | null;
    target_days: number;
  }[];
  top_issues: {
    title: string;
    plain: string;
    severity: string;
    rules: string[];
    count: number;
    honeypot: number;
    ai_reviewed: number;
    external: number;
    latest_id: string;
    latest_number: string;
  }[];
  trend: { day: string; opened: number; resolved: number }[];
  containment: {
    external_attack_sessions: number;
    contained: number;
    honeypot: number;
    rate: number | null;
    real_data_changes: number;
    definition: string;
  };
  ai_coverage: { open_issues: number; ai_reviewed: number; rate: number | null };
}
export interface WorkspaceAnswer extends AIGeneration {
  answer: string;
  confidence: string;
  references: { case_id: string; reason: string }[];
  limitations: string[];
}
export interface ModelCatalogue {
  source: "live" | "suggestions";
  items: { id: string; label: string; note: string }[];
  note: string;
  error?: string;
}
export interface TelegramStatus {
  configured: boolean;
  mode: string;
  bot_username: string | null;
  last_poll_at: string | null;
  last_error: string | null;
  counts: { pending: number; approved: number };
  public_url: string;
}
export interface TelegramUser {
  id: string;
  telegram_user_id: number | string;
  username: string | null;
  display_name: string | null;
  status: "pending" | "approved" | "rejected" | "revoked";
  role: "viewer" | "analyst" | "approver" | null;
  requested_at: string;
  decided_at: string | null;
  decided_by: string | null;
  last_notified_at: string | null;
}
