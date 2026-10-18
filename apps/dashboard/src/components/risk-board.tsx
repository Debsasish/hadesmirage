import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, Ghost, Globe2, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "../api";
import { ErrorState, Loading } from "../components";
import { useLens, plainRules } from "../experience";
import type { BoardData } from "../types";
import { SeverityPill } from "./issue-panel";

function Gauge({
  value,
  max,
  label,
  sub,
  tone,
}: {
  value: number | null;
  max: number;
  label: string;
  sub: string;
  tone: string;
}) {
  const ratio = value === null ? 0 : Math.min(1, value / max);
  const angle = Math.PI * (1 - ratio);
  const x = 60 + 46 * Math.cos(angle);
  const y = 60 - 46 * Math.sin(angle);
  return (
    <div className="gauge">
      <svg viewBox="0 0 120 70" aria-hidden="true">
        <path d="M14 60 A46 46 0 0 1 106 60" className="gauge-track" />
        {value !== null && ratio > 0 && (
          <path
            d={`M14 60 A46 46 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`}
            className={`gauge-value tone-${tone}`}
          />
        )}
      </svg>
      <strong>{label}</strong>
      <span>{sub}</span>
    </div>
  );
}

function age(days: number | null) {
  if (days === null) return "—";
  if (days < 1) return `${Math.max(1, Math.round(days * 24))} h`;
  return `${Math.round(days)} days`;
}

function TrendChart({ data }: { data: BoardData["trend"] }) {
  const max = Math.max(1, ...data.map((item) => Math.max(item.opened, item.resolved)));
  const point = (index: number, value: number) =>
    `${20 + (index * 560) / Math.max(1, data.length - 1)},${150 - (value / max) * 120}`;
  let openedTotal = 0;
  let resolvedTotal = 0;
  const opened = data.map((item, index) =>
    point(index, (openedTotal += item.opened) / Math.max(1, data.length / 6)),
  );
  const resolved = data.map((item, index) =>
    point(index, (resolvedTotal += item.resolved) / Math.max(1, data.length / 6)),
  );
  return (
    <div className="trend-chart">
      <div className="trend-legend">
        <span className="legend-opened">Opened</span>
        <span className="legend-resolved">Resolved</span>
      </div>
      <svg
        viewBox="0 0 600 175"
        role="img"
        aria-label={`Issues opened ${openedTotal} and resolved ${resolvedTotal} in 30 days`}
      >
        <line x1="20" x2="580" y1="150" y2="150" className="trend-axis" />
        <polyline points={opened.join(" ")} className="trend-opened" />
        <polyline points={resolved.join(" ")} className="trend-resolved" />
        <text x="20" y="168">
          {data[0]?.day.slice(5)}
        </text>
        <text x="300" y="168" textAnchor="middle">
          {data[15]?.day.slice(5)}
        </text>
        <text x="580" y="168" textAnchor="end">
          {data[data.length - 1]?.day.slice(5)}
        </text>
      </svg>
      <p className="helper">
        {openedTotal} opened · {resolvedTotal} resolved in 30 days (cumulative)
      </p>
    </div>
  );
}

export function RiskBoard() {
  const { plain } = useLens();
  const navigate = useNavigate();
  const result = useQuery({
    queryKey: ["board"],
    queryFn: () => api<BoardData>("/v1/board"),
    refetchInterval: 20_000,
  });
  if (result.isPending) return <Loading label="Building the risk board..." />;
  if (result.isError)
    return <ErrorState error={result.error} retry={() => void result.refetch()} />;
  const data = result.data;
  const letters = { critical: "C", high: "H", medium: "M", low: "L" } as const;
  return (
    <section className="risk-board" aria-label="Risk board">
      <div className="board-grid">
        <article className="board-card">
          <h2>Open issues</h2>
          <ul className="severity-list">
            {data.severity.map((item) => (
              <li key={item.level}>
                <span className={`sev-letter sev-${item.level}`}>{letters[item.level]}</span>
                <div>
                  <strong>{item.open}</strong>
                  <small>{item.level[0].toUpperCase() + item.level.slice(1)} issues</small>
                </div>
                <span
                  className={`change-badge ${item.change_percent === null || item.change_percent === 0 ? "flat" : item.change_percent > 0 ? "up" : "down"}`}
                  title="New this week compared with the previous week"
                >
                  {item.change_percent === null ? (
                    `${item.opened_7d} new`
                  ) : (
                    <>
                      {item.change_percent > 0 ? (
                        <TrendingUp size={12} />
                      ) : (
                        <TrendingDown size={12} />
                      )}
                      {Math.abs(item.change_percent)}%
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </article>
        <article className="board-card">
          <h2>Average issue age</h2>
          <p className="board-sub">Current open issues</p>
          <div className="gauge-grid">
            {data.severity.map((item) => (
              <Gauge
                key={item.level}
                value={item.average_age_days}
                max={item.target_days * 2}
                label={age(item.average_age_days)}
                sub={`${item.level[0].toUpperCase() + item.level.slice(1)} · target ${item.target_days} d`}
                tone={
                  item.average_age_days !== null && item.average_age_days > item.target_days
                    ? "red"
                    : "green"
                }
              />
            ))}
          </div>
        </article>
        <article className="board-card">
          <h2>{plain ? "Attackers contained" : "Containment rate"}</h2>
          <p className="board-sub">
            {plain ? "Outside agents we caught and limited" : data.containment.definition}
          </p>
          <div className="score-gauge">
            <Gauge
              value={data.containment.rate}
              max={100}
              label={data.containment.rate === null ? "—" : `${data.containment.rate}%`}
              sub={`${data.containment.contained} of ${data.containment.external_attack_sessions} sessions`}
              tone="green"
            />
          </div>
          <p className="board-foot">
            <Ghost size={14} /> {data.containment.honeypot} moved to honeypot ·{" "}
            {data.containment.real_data_changes} real data changes
          </p>
        </article>
        <article className="board-card">
          <h2>{plain ? "AI help" : "AI coverage"}</h2>
          <div className="compliance-grid">
            <div>
              <BrainCircuit size={28} />
              <strong>AI-reviewed issues</strong>
              <span>{data.ai_coverage.rate === null ? "—" : `${data.ai_coverage.rate}%`}</span>
              <div className="mini-bar">
                <i style={{ width: `${data.ai_coverage.rate ?? 0}%` }} />
              </div>
            </div>
            <div>
              <Ghost size={28} />
              <strong>Honeypot sessions</strong>
              <span>{data.containment.honeypot}</span>
              <div className="mini-bar purple">
                <i
                  style={{
                    width: `${data.containment.external_attack_sessions ? (data.containment.honeypot * 100) / data.containment.external_attack_sessions : 0}%`,
                  }}
                />
              </div>
            </div>
          </div>
        </article>
      </div>
      <div className="board-grid board-grid-wide">
        <article className="board-card">
          <h2>Top issues</h2>
          <p className="board-sub">{data.top_issues.length} rules with open issues</p>
          <table className="top-issues">
            <thead>
              <tr>
                <th>{plain ? "What happened" : "Rule"}</th>
                <th>Issues</th>
                <th>Risks</th>
                <th>Severity</th>
              </tr>
            </thead>
            <tbody>
              {data.top_issues.map((item) => (
                <tr
                  key={`${item.title}-${item.severity}`}
                  tabIndex={0}
                  onClick={() => navigate(`/incidents?issue=${item.latest_id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") navigate(`/incidents?issue=${item.latest_id}`);
                  }}
                >
                  <td>
                    <span className="rule-cell">
                      {plain
                        ? item.rules[0]
                          ? (plainRules[item.rules[0]] ?? item.plain)
                          : item.plain
                        : item.title}
                    </span>
                  </td>
                  <td>{item.count}</td>
                  <td className="risk-icons">
                    {!!item.external && <Globe2 size={15} aria-label="From outside" />}
                    {!!item.honeypot && <Ghost size={15} aria-label="Moved to honeypot" />}
                    {!!item.ai_reviewed && <BrainCircuit size={15} aria-label="AI reviewed" />}
                  </td>
                  <td>
                    <SeverityPill value={item.severity} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
        <article className="board-card">
          <h2>Opened and resolved issues</h2>
          <p className="board-sub">Past 30 days</p>
          <TrendChart data={data.trend} />
        </article>
      </div>
    </section>
  );
}
