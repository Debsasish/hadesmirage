import { useId } from "react";
import { ArrowRight, GitBranch, History, RotateCcw, ShieldCheck } from "lucide-react";
import { Button, Status, time } from "../components";
import type { EventRecord, RouteMode, Session } from "../types";

export const routeNames: Record<RouteMode, string> = {
  PRODUCTION: "Production",
  RESTRICTED: "Restricted",
  DECOY_PENDING: "Preparing",
  DECOY: "Synthetic",
  TERMINATED: "Terminated",
};

const routeMeaning: Record<RouteMode, string> = {
  PRODUCTION: "The protected path still required identity, tool and resource authorization.",
  RESTRICTED: "New production dispatch was fenced. Already committed work was not undone.",
  DECOY_PENDING: "A synthetic template was being reserved. Production remained blocked.",
  DECOY: "Eligible supported requests used isolated synthetic state, not production records.",
  TERMINATED: "Production and decoy dispatch stopped. Production access was not restored.",
};

interface RouteLensProps {
  session: Session;
  events: EventRecord[];
  inspectedVersion: number | null;
  onInspect: (version: number | null) => void;
  onEvidence: (event: EventRecord) => void;
}

export function RouteLens({
  session,
  events,
  inspectedVersion,
  onInspect,
  onEvidence,
}: RouteLensProps) {
  const helpId = useId();
  const history = session.history;
  const stage = history.find((item) => item.version === inspectedVersion) ?? history.at(-1);
  if (!stage) {
    return (
      <div className="route-lens-unavailable" role="status">
        No recorded route history is available. No route or backend effect is inferred.
      </div>
    );
  }
  const stageIndex = history.indexOf(stage);
  const isLatest = stage.version === session.route_version;
  const inRoute = events.filter((event) => event.body.route_mode === stage.mode);
  const denied = inRoute.filter((event) => event.outcome === "deny").length;
  const simulated = inRoute.filter((event) => event.outcome === "simulated").length;
  return (
    <section className="route-lens" data-route={stage.mode} aria-label="Read-only route lens">
      <header className="lens-caption">
        <span>
          <GitBranch size={16} />
          Route lens
        </span>
        <span className="lens-readonly">
          <ShieldCheck size={13} />
          Read only
        </span>
      </header>
      <div className="lens-current-route">
        <span>Latest received route</span>
        <Status value={session.route_mode} />
        <span>v{session.route_version}</span>
      </div>
      <div className="lens-checkpoint" aria-live="polite" aria-atomic="true">
        <div>
          <span className="checkpoint-version">v{stage.version}</span>
          <h4>{routeNames[stage.mode]}</h4>
        </div>
        <span className="checkpoint-kind">
          {isLatest ? "Latest recorded state" : "Historical state"}
        </span>
        <p>{routeMeaning[stage.mode]}</p>
      </div>
      <ol className="case-route-track lens-stops" aria-label="Session route history">
        {history.map((entry, index) => (
          <li
            key={entry.version}
            data-mode={entry.mode}
            data-inspected={stage.version === entry.version}
            data-passed={index <= stageIndex}
          >
            <button
              type="button"
              title={`Inspect ${routeNames[entry.mode]} v${entry.version}`}
              aria-pressed={stage.version === entry.version}
              onClick={() => onInspect(entry.version)}
            >
              <span className="route-track-dot" />
              <strong>{routeNames[entry.mode]}</strong>
              <small>v{entry.version}</small>
            </button>
          </li>
        ))}
      </ol>
      <label className="lens-scrubber">
        <span>
          <History size={14} />
          Inspect route history
        </span>
        <input
          type="range"
          min={0}
          max={Math.max(1, history.length - 1)}
          step={1}
          value={stageIndex}
          disabled={history.length < 2}
          aria-describedby={helpId}
          aria-valuetext={`Version ${stage.version}, ${routeNames[stage.mode]}, ${isLatest ? "latest recorded state" : "historical state"}`}
          onChange={(event) => onInspect(history[Number(event.target.value)].version)}
        />
      </label>
      <div className="lens-time-row">
        <time>{time(stage.at)}</time>
        <Button
          variant="ghost"
          disabled={inspectedVersion === null}
          onClick={() => onInspect(null)}
        >
          <RotateCcw size={13} />
          Latest
        </Button>
      </div>
      <p id={helpId} className="lens-scope">
        Inspecting history changes this view only. It never replays requests or restores production
        access.
      </p>
      <div className="lens-observation-counts">
        <span>
          <strong>{inRoute.length}</strong> linked in this route
        </span>
        <span>
          <strong>{denied}</strong> denied
        </span>
        <span>
          <strong>{simulated}</strong> simulated
        </span>
      </div>
      <div className="lens-observations">
        {inRoute.length ? (
          inRoute
            .slice(-2)
            .reverse()
            .map((event) => (
              <button type="button" key={event.id} onClick={() => onEvidence(event)}>
                <span>
                  <strong>{event.body.attributes.tool ?? event.event_type}</strong>
                  <small>
                    {event.body.attributes.reason_code?.replaceAll("_", " ") ??
                      "Recorded observation"}
                  </small>
                </span>
                <Status value={event.outcome} />
                <ArrowRight size={14} />
              </button>
            ))
        ) : (
          <p>
            No case-linked observation is recorded in this route. That is not proof that no traffic
            occurred.
          </p>
        )}
      </div>
    </section>
  );
}
