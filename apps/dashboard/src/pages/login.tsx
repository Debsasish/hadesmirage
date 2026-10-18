import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import { ArrowRight, Check, Eye, EyeOff, KeyRound, Moon, ShieldCheck, Sun } from "lucide-react";
import { api, post, setCsrf } from "../api";
import { Badge, Button, Field } from "../components";
import { Logo } from "../shell";
import { useMe, useWorkspace } from "../state";
import type { Me } from "../types";

export function LoginPage() {
  const me = useMe();
  const client = useQueryClient();
  const { theme, setTheme } = useWorkspace();
  const [username, setUsername] = useState("admin");
  const [code, setCode] = useState("");
  const [showCode, setShowCode] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const roleNotes: Record<string, { purpose: string; permissions: string[] }> = {
    admin: {
      purpose: "Configure the boundary. Review the evidence.",
      permissions: [
        "Investigate tenant-scoped cases",
        "Activate separately reviewed policies",
        "Run bounded synthetic scenarios",
      ],
    },
    analyst: {
      purpose: "Work the case without widening authority.",
      permissions: [
        "Read cases and linked observations",
        "Restrict or terminate sessions",
        "Record notes and export evidence",
      ],
    },
    approver: {
      purpose: "Review one exact action before it runs.",
      permissions: [
        "Inspect the full action digest",
        "Approve or reject another requester's action",
        "Review tested policy candidates",
      ],
    },
  };
  const login = useMutation({
    mutationFn: async () => {
      const response = await post<{ csrf: string }>("/auth/login", { username, access_code: code });
      setCsrf(response.csrf);
      return api<Me>("/auth/me");
    },
    onSuccess: (identity) => {
      client.clear();
      client.setQueryData(["me"], identity);
    },
  });
  if (me.data) return <Navigate to="/overview" replace />;
  return (
    <div className="login-page">
      <header className="login-topline">
        <Logo />
        <div>
          <span>Native laboratory</span>
          <button
            type="button"
            className="icon-button"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </header>
      <div className="login-story">
        <div className="login-message">
          <h1>
            Make every
            <br />
            decision traceable.
          </h1>
          <p>
            Agent permissions, security evidence and isolated synthetic sessions. One clear
            workspace.
          </p>
          <div
            className="login-boundary-diagram"
            aria-label="Application enforcement precedes protected dispatch or eligible synthetic routing"
          >
            <div className="login-request">
              <span className="request-glyph">
                <ShieldCheck size={21} />
              </span>
              <div>
                <strong>Every protected request</strong>
                <small>Verified identity and exact scope</small>
              </div>
            </div>
            <div className="login-fence">
              <span />
              Policy before dispatch
              <span />
            </div>
            <div className="login-route-options">
              <div>
                <span className="route-option-marker production" />
                <strong>Authorized</strong>
                <small>Protected backend</small>
              </div>
              <div>
                <span className="route-option-marker synthetic" />
                <strong>Restricted first</strong>
                <small>Eligible synthetic session</small>
              </div>
            </div>
          </div>
          <p className="login-core-rule">
            AI supports investigation.
            <br />
            <strong>It never grants authority.</strong>
          </p>
        </div>
        <div className="login-story-footer">
          <span>Hades Mirage</span>
          <span>Deterministic authority. Advisory investigation.</span>
        </div>
      </div>
      <div className="login-form-wrap">
        <div className="login-form">
          <div className="login-environment">
            <Badge tone="teal">P1-native</Badge>
            <span>Local synthetic workspace</span>
          </div>
          <div className="login-form-heading">
            <h2>Enter your workspace</h2>
            <p>
              Choose your fixture role and enter the launch code. All records and operations here
              are synthetic.
            </p>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!login.isPending) login.mutate();
            }}
          >
            <Field label="Local identity">
              <select
                aria-label="Local identity"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              >
                <option value="admin">Alex Morgan / Security administrator</option>
                <option value="analyst">Jordan Lee / SOC analyst</option>
                <option value="approver">Sam Rivera / Independent approver</option>
              </select>
            </Field>
            <div className="login-role-preview" aria-live="polite">
              <p>{roleNotes[username].purpose}</p>
              <ul>
                {roleNotes[username].permissions.map((permission) => (
                  <li key={permission}>
                    <Check size={14} />
                    {permission}
                  </li>
                ))}
              </ul>
            </div>
            <Field
              label="Local access code"
              help="Printed by the native launcher. Also stored in .local\runtime-secrets.json."
            >
              <div className="input-with-icon">
                <KeyRound size={16} />
                <input
                  type={showCode ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  aria-label="Local access code"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  onKeyUp={(event) => setCapsLock(event.getModifierState("CapsLock"))}
                  placeholder="Enter the generated access code"
                />
                <button
                  type="button"
                  className="access-code-toggle"
                  aria-label={showCode ? "Hide local access code" : "Show local access code"}
                  onClick={() => setShowCode(!showCode)}
                >
                  {showCode ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </Field>
            {capsLock && (
              <p className="caps-lock-note" role="status">
                Caps Lock is on.
              </p>
            )}
            {login.isError && (
              <div className="form-error" role="alert">
                {login.error.message}
              </div>
            )}
            <Button type="submit" variant="primary" busy={login.isPending} className="full-width">
              Open analyst console
              <ArrowRight size={16} />
            </Button>
          </form>
          <div className="login-hint">
            <ShieldCheck size={17} />
            <p>
              Fixture authentication is loopback-only, not enterprise SSO. A separate fixture
              identity is required to review another actor's action.
            </p>
          </div>
          <div className="login-command">
            <span>Start without Docker</span>
            <code>.\.venv\Scripts\python.exe -m mirage run</code>
          </div>
        </div>
      </div>
    </div>
  );
}
