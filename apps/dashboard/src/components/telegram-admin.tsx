import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BellRing, Check, Send, ShieldOff, X } from "lucide-react";
import { api, post } from "../api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  KeyValue,
  Loading,
  Panel,
  Status,
  ago,
} from "../components";
import { useAction, useMe } from "../state";
import type { TelegramStatus, TelegramUser } from "../types";

const ROLES = [
  { value: "viewer", label: "Viewer — gets alerts only" },
  { value: "analyst", label: "Analyst — alerts + issue summaries" },
  { value: "approver", label: "Approver — can approve or reject actions" },
] as const;

function UserRow({ user }: { user: TelegramUser }) {
  const [role, setRole] = useState<string>(user.role ?? "viewer");
  const decide = useAction(
    (decision: "approve" | "reject") =>
      post(`/v1/telegram/users/${user.id}/decision`, {
        decision,
        role: decision === "approve" ? role : null,
      }),
    "Telegram access decision saved and the user was notified.",
  );
  const changeRole = useAction(
    (value: string) => post(`/v1/telegram/users/${user.id}/role`, { role: value }),
    "Telegram role updated.",
  );
  const revoke = useAction(
    () => post(`/v1/telegram/users/${user.id}/revoke`, {}),
    "Telegram access revoked. Pending approval buttons stop working.",
  );
  const name = user.display_name || user.username || `Telegram user ${user.telegram_user_id}`;
  return (
    <div className="telegram-user">
      <div>
        <strong>{name}</strong>
        <p>
          {user.username ? `@${user.username} · ` : ""}requested {ago(user.requested_at)}
          {user.decided_by ? ` · decided by ${user.decided_by}` : ""}
        </p>
      </div>
      <div className="telegram-actions">
        <Status
          value={
            user.status === "approved"
              ? "approved"
              : user.status === "pending"
                ? "pending"
                : user.status
          }
        />
        {user.status !== "revoked" && user.status !== "rejected" && (
          <select
            aria-label={`Telegram role for ${name}`}
            value={role}
            onChange={(event) => {
              setRole(event.target.value);
              if (user.status === "approved") changeRole.mutate(event.target.value);
            }}
          >
            {ROLES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        )}
        {user.status === "pending" && (
          <>
            <Button
              variant="primary"
              busy={decide.isPending}
              onClick={() => decide.mutate("approve")}
            >
              <Check size={14} />
              Approve
            </Button>
            <Button busy={decide.isPending} onClick={() => decide.mutate("reject")}>
              <X size={14} />
              Reject
            </Button>
          </>
        )}
        {user.status === "approved" && (
          <Button busy={revoke.isPending} onClick={() => revoke.mutate()}>
            <ShieldOff size={14} />
            Revoke
          </Button>
        )}
      </div>
    </div>
  );
}

export function TelegramPanel() {
  const me = useMe();
  const admin = me.data?.principal.roles.includes("security_admin");
  const status = useQuery({
    queryKey: ["telegram"],
    queryFn: () => api<TelegramStatus>("/v1/telegram"),
    retry: false,
    refetchInterval: 15_000,
  });
  const users = useQuery({
    queryKey: ["telegram-users"],
    queryFn: () => api<{ items: TelegramUser[] }>("/v1/telegram/users"),
    enabled: !!admin,
    retry: false,
    refetchInterval: 15_000,
  });
  const test = useAction(
    () => post<{ sent: number; failed: number }>("/v1/telegram/test", {}),
    "Test notification sent to approved Telegram users.",
  );
  return (
    <Panel
      title="Telegram approvals & alerts"
      subtitle="People connect to the bot, an admin approves them and picks what they may do."
      action={<BellRing size={17} />}
    >
      <div className="panel-body">
        {status.isPending ? (
          <Loading label="Checking the Telegram connection..." />
        ) : status.isError ? (
          <ErrorState error={status.error} retry={() => void status.refetch()} />
        ) : (
          <>
            <dl className="detail-list">
              <KeyValue label="Bot">
                {status.data.configured
                  ? `@${status.data.bot_username ?? "configured"}`
                  : "Not connected — add a bot token on the server"}
              </KeyValue>
              <KeyValue label="Mode">{status.data.mode}</KeyValue>
              <KeyValue label="Last contact">
                {status.data.last_poll_at ? ago(status.data.last_poll_at) : "Never"}
              </KeyValue>
              <KeyValue label="People">
                {status.data.counts.approved} approved · {status.data.counts.pending} waiting
              </KeyValue>
            </dl>
            {status.data.last_error && (
              <p className="error-text" role="alert">
                {status.data.last_error}
              </p>
            )}
            <div className="callout">
              <BellRing size={16} />
              <div>
                In Telegram, a person sends <strong>/start</strong> to the bot. They appear below as
                waiting. Approvers get Approve / Reject buttons for sensitive actions; each button
                works once and only for that exact request. Telegram can never grant administrator
                rights.
              </div>
            </div>
          </>
        )}
        {admin ? (
          users.isPending ? (
            <Loading label="Loading Telegram users..." />
          ) : users.isError ? (
            <ErrorState error={users.error} retry={() => void users.refetch()} />
          ) : users.data.items.length ? (
            <div className="telegram-users">
              {users.data.items.map((user) => (
                <UserRow key={`${user.id}-${user.status}-${user.role}`} user={user} />
              ))}
            </div>
          ) : (
            <Empty
              title="No Telegram requests yet"
              description="Ask people to send /start to your bot."
            />
          )
        ) : (
          <p className="helper">A security administrator manages Telegram access.</p>
        )}
        {admin && (
          <Button
            busy={test.isPending}
            disabled={!status.data?.configured}
            onClick={() => test.mutate()}
          >
            <Send size={14} />
            Send test alert
          </Button>
        )}
        <Badge tone="neutral" dot={false}>
          Approvals from Telegram use the same exact-request checks as the console
        </Badge>
      </div>
    </Panel>
  );
}
