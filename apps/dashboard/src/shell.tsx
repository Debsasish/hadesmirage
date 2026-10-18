import { Fragment, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  Bell,
  BookOpen,
  Boxes,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Command,
  FileClock,
  Ghost,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings2,
  ShieldCheck,
  ShieldHalf,
  SlidersHorizontal,
  Sparkles,
  Sun,
  UsersRound,
} from "lucide-react";
import { api, ApiError } from "./api";
import { Badge, Button, Empty, ErrorState, Loading, Modal, Status, ago } from "./components";
import { useLogout, useMe, useOverview, useWorkspace } from "./state";
import { ScenarioDialog } from "./pages/overview";
import type { Incident, Principal } from "./types";
import { LensToggle } from "./experience";
import { AIChatLauncher, AIChatPanel } from "./components/ai-chat";

const navigation = [
  { path: "/overview", label: "Boards", icon: LayoutDashboard },
  { path: "/incidents", label: "Issues", icon: ShieldHalf },
  { path: "/agents", label: "AI agents", icon: UsersRound },
  { path: "/architecture", label: "Attack map", icon: Network },
  { path: "/guardrails", label: "Access rules", icon: SlidersHorizontal },
  { path: "/deception", label: "Honeypot", icon: Ghost },
  { path: "/audit", label: "Reports", icon: FileClock },
  { path: "/integrations", label: "Connect", icon: Boxes },
  { path: "/settings", label: "Settings", icon: Settings2 },
];

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand">
      <span className="brand-mark">
        <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <path
            d="M6 25V8l10 9L26 8v17M11 25v-6l5 5 5-5v6"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      {!compact && (
        <span>
          <strong>
            Hades <span>Mirage</span>
          </strong>
          <small>Security operations</small>
        </span>
      )}
    </div>
  );
}

function Navigation({
  onNavigate,
  compact = false,
}: {
  onNavigate?: () => void;
  compact?: boolean;
}) {
  const overview = useOverview();
  const groups: Record<number, string> = { 0: "Operate", 2: "Control", 5: "Workspace" };
  return (
    <nav aria-label="Main navigation">
      {navigation.map(({ path, label, icon: Icon }, index) => {
        const count =
          path === "/incidents"
            ? overview.data?.open_incidents
            : path === "/deception"
              ? overview.data?.active_decoys
              : undefined;
        return (
          <Fragment key={path}>
            {groups[index] && <div className="nav-group-label">{groups[index]}</div>}
            <NavLink
              to={path}
              onClick={onNavigate}
              title={label}
              aria-label={compact ? `${label}${count ? ` ${count}` : ""}` : undefined}
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              <Icon size={18} strokeWidth={1.7} />
              <span>{label}</span>
              {path === "/incidents" && !!overview.data?.open_incidents && (
                <span className="nav-count">{overview.data.open_incidents}</span>
              )}
              {path === "/deception" && !!overview.data?.active_decoys && (
                <span className="nav-count nav-count-purple">{overview.data.active_decoys}</span>
              )}
            </NavLink>
          </Fragment>
        );
      })}
    </nav>
  );
}

function SearchDialog({ open, setOpen }: { open: boolean; setOpen: (value: boolean) => void }) {
  const [query, setQuery] = useState("");
  const result = useQuery({
    queryKey: ["search", query],
    queryFn: () =>
      api<{ incidents: Incident[]; agents: Principal[] }>(
        `/v1/search?q=${encodeURIComponent(query)}`,
      ),
    enabled: open && query.trim().length >= 2,
    retry: false,
  });
  return (
    <Modal
      open={open}
      onOpenChange={setOpen}
      title="Search the workspace"
      description="Find tenant-scoped incidents and registered agents. No external sources are queried."
    >
      <div className="search-field large">
        <Search size={18} />
        <input
          autoFocus
          aria-label="Search incidents and agents"
          placeholder="Case number, signal, or agent name..."
          maxLength={100}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <kbd>ESC</kbd>
      </div>
      {query.length < 2 ? (
        <Empty
          title="Start with two characters"
          description="Try a case number such as HM-0001, or search for procurement."
        />
      ) : result.isPending ? (
        <Loading label="Searching authorized records..." />
      ) : result.isError ? (
        <ErrorState error={result.error} />
      ) : (
        <div className="search-results">
          {result.data?.incidents.map((item) => (
            <Link key={item.id} to={`/incidents/${item.id}`} onClick={() => setOpen(false)}>
              <ShieldHalf size={18} />
              <div>
                <strong>
                  {item.number} / {item.title}
                </strong>
                <small>{item.principal_id}</small>
              </div>
              <ChevronRight size={15} />
            </Link>
          ))}
          {result.data?.agents.map((item) => (
            <Link key={item.id} to={`/agents?agent=${item.id}`} onClick={() => setOpen(false)}>
              <UsersRound size={18} />
              <div>
                <strong>{item.name}</strong>
                <small>{item.id}</small>
              </div>
              <ChevronRight size={15} />
            </Link>
          ))}
          {!result.data?.incidents.length && !result.data?.agents.length && (
            <Empty
              title="No matching records"
              description="Search is limited to your verified tenant."
            />
          )}
        </div>
      )}
    </Modal>
  );
}

export function Shell() {
  const me = useMe();
  const overview = useOverview();
  const {
    theme,
    setTheme,
    hours,
    setHours,
    origin,
    setOrigin,
    setScenarioOpen,
    sidebarCompact,
    setSidebarCompact,
  } = useWorkspace();
  const [searchOpen, setSearchOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const logout = useLogout();
  const location = useLocation();
  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((current) => !current);
      }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);
  if (me.isPending)
    return (
      <div className="boot-screen">
        <Logo />
        <Loading label="Verifying your local session..." />
      </div>
    );
  if (me.error instanceof ApiError && me.error.status === 401)
    return <Navigate to="/login" replace />;
  if (me.isError || !me.data)
    return (
      <div className="boot-screen">
        <Logo />
        <ErrorState error={me.error} retry={() => void me.refetch()} />
      </div>
    );
  const identity = me.data;
  const active = navigation.find((item) => location.pathname.startsWith(item.path));
  const notifications =
    (overview.data?.open_incidents ?? 0) + (overview.data?.pending_approvals ?? 0);
  return (
    <div className={`app-shell soc-shell ${sidebarCompact ? "sidebar-compact" : ""}`}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="productbar">
        <div className="productbar-identity">
          <Link to="/overview" className="brand-link">
            <Logo />
          </Link>
          <span className="productbar-divider" />
          <span className="productbar-product">Analyst workspace</span>
        </div>
        <div className="productbar-tools">
          <LensToggle />
          <button
            className="global-search"
            onClick={() => setSearchOpen(true)}
            aria-label="Search workspace K"
            aria-keyshortcuts="Control+K Meta+K"
          >
            <Search size={16} />
            <span>Search workspace</span>
            <kbd aria-hidden="true">
              <Command size={10} /> K
            </kbd>
          </button>
          <button
            className="icon-button"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button
            className="icon-button notification-button"
            aria-label={`Open notifications, ${notifications} items`}
            onClick={() => setNotificationsOpen(true)}
          >
            <Bell size={18} />
            {!!notifications && <span />}
          </button>
          <button
            className="account-button"
            onClick={() => setAccountOpen(true)}
            aria-label={`Open account menu ${identity.principal.name
              .split(" ")
              .map((name) => name[0])
              .join("")
              .slice(0, 2)}`}
          >
            <span className="avatar" aria-hidden="true">
              {identity.principal.name
                .split(" ")
                .map((name) => name[0])
                .join("")
                .slice(0, 2)}
            </span>
            <ChevronDown size={12} />
          </button>
        </div>
      </header>
      <aside className="sidebar">
        <button className="workspace-switch" onClick={() => setAccountOpen(true)}>
          <span className="workspace-avatar">M</span>
          <span>
            <strong>{identity.tenant.name}</strong>
            <small>Synthetic laboratory</small>
          </span>
          <ChevronDown size={14} />
        </button>
        <Navigation compact={sidebarCompact} />
        <div className="sidebar-bottom">
          <div className="sidebar-boundary">
            <ShieldCheck size={19} />
            <div>
              <strong>Enforcement is deterministic</strong>
              <p>Investigation stays advisory.</p>
            </div>
          </div>
          <Link
            to="/settings"
            className="sidebar-profile"
            title="P1-native profile and limitations"
            aria-label={sidebarCompact ? "P1-native profile" : undefined}
          >
            <span className="profile-square">P1</span>
            <span>
              Native local profile<small>No cloud or gateway claim</small>
            </span>
            <ArrowUpRight size={14} />
          </Link>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={20} />
            </button>
            <button
              className="icon-button desktop-navigation-toggle"
              aria-label={sidebarCompact ? "Expand navigation" : "Collapse navigation"}
              aria-expanded={!sidebarCompact}
              onClick={() => setSidebarCompact(!sidebarCompact)}
              title={sidebarCompact ? "Expand navigation" : "Collapse navigation"}
            >
              {sidebarCompact ? <PanelLeftOpen size={19} /> : <PanelLeftClose size={19} />}
            </button>
            <span className="topbar-workspace">Workspace</span>
            <ChevronRight size={13} className="muted" />
            <strong>{active?.label ?? "Incident workbench"}</strong>
            <Badge dot={false} tone="neutral">
              {identity.profile}
            </Badge>
          </div>
          <div className="workspace-role">
            <span className="role-indicator" />
            {identity.principal.roles.includes("security_admin")
              ? "Security administrator"
              : identity.principal.roles.includes("approver")
                ? "Independent approver"
                : "SOC analyst"}
          </div>
        </header>
        <div className="context-bar">
          <div className="row">
            <span className="context-label">
              <span className="tiny-dot" />
              Local laboratory
            </span>
            <span className="context-separator" />
            <span className="muted small">All records are synthetic</span>
          </div>
          <div className="row context-controls">
            <span className="model-state">
              <Sparkles size={15} />
              {identity.model_provider === "fixture"
                ? "Demo AI (fixture)"
                : identity.model_provider === "gemini"
                  ? "Gemini AI"
                  : "AI off"}
            </span>
            <select
              aria-label="Data source"
              value={origin}
              onChange={(event) =>
                setOrigin(
                  event.target.value === "live"
                    ? "live"
                    : event.target.value === "laboratory"
                      ? "laboratory"
                      : "all",
                )
              }
            >
              <option value="all">All recorded sources</option>
              <option value="laboratory">Lab executions</option>
              <option value="live">Direct API requests</option>
            </select>
            {location.pathname === "/overview" && (
              <select
                aria-label="Time range"
                title="Overview activity window"
                value={hours}
                onChange={(event) =>
                  setHours(event.target.value === "1" ? 1 : event.target.value === "168" ? 168 : 24)
                }
              >
                <option value={1}>Last hour</option>
                <option value={24}>Last 24 hours</option>
                <option value={168}>Last 7 days</option>
              </select>
            )}
          </div>
        </div>
        <main id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>
            <ShieldCheck size={12} /> Application boundary / synthetic environment
          </span>
          <span>
            {overview.isError
              ? "API status unavailable"
              : (overview.data?.policy_version ?? "Loading policy")}
            <span className="footer-dot" />
            v0.1.0
            <Link to="/settings">
              Profile & limitations
              <ArrowUpRight size={11} />
            </Link>
          </span>
        </footer>
      </div>
      <SearchDialog open={searchOpen} setOpen={setSearchOpen} />
      <AIChatLauncher />
      <AIChatPanel />
      <Modal
        open={mobileOpen}
        onOpenChange={setMobileOpen}
        title="Workspace navigation"
        description="Hades Mirage analyst console"
        drawer
      >
        <Navigation onNavigate={() => setMobileOpen(false)} />
      </Modal>
      <Modal
        open={notificationsOpen}
        onOpenChange={setNotificationsOpen}
        title="Notification centre"
        description="Current review items from stored local records."
      >
        {overview.isPending ? (
          <Loading />
        ) : overview.isError ? (
          <ErrorState error={overview.error} />
        ) : (
          <>
            <Link
              className="notification-item"
              to="/guardrails?tab=approvals"
              onClick={() => setNotificationsOpen(false)}
            >
              <BookOpen size={20} />
              <span>
                <strong>{overview.data?.pending_approvals ?? 0} pending approvals</strong>
                <small>Exact actions require a separate reviewer.</small>
              </span>
              <ChevronRight size={15} />
            </Link>
            {overview.data?.recent_incidents
              .filter((item) => item.status !== "resolved")
              .map((item) => (
                <Link
                  key={item.id}
                  to={`/incidents/${item.id}`}
                  className="notification-item"
                  onClick={() => setNotificationsOpen(false)}
                >
                  <ShieldHalf size={20} />
                  <span>
                    <strong>
                      {item.number} / {item.title}
                    </strong>
                    <small>
                      {ago(item.updated_at)} / {item.origin}
                    </small>
                  </span>
                  <Status value={item.severity} />
                </Link>
              ))}
            {!overview.data?.open_incidents && !overview.data?.pending_approvals && (
              <Empty title="Nothing requires review" />
            )}
          </>
        )}
      </Modal>
      <Modal
        open={accountOpen}
        onOpenChange={setAccountOpen}
        title="Your workspace"
        description="Verified local fixture identity. Role changes require a new sign-in."
      >
        <div className="account-detail">
          <span className="avatar large">{identity.principal.name[0]}</span>
          <div>
            <h3>{identity.principal.name}</h3>
            <p className="mono">{identity.principal.id}</p>
          </div>
        </div>
        <div className="row wrap">
          {identity.principal.roles.map((role) => (
            <Badge key={role} tone="teal">
              {role.replaceAll("_", " ")}
            </Badge>
          ))}
        </div>
        <div className="callout">
          <CircleHelp size={18} />
          <div>
            These are local synthetic identities, not enterprise SSO. The access code is generated
            by the native launcher and kept outside source control.
          </div>
        </div>
        {logout.isError && (
          <p role="alert" className="error-text">
            {logout.error.message}
          </p>
        )}
        <div className="dialog-actions">
          <Button
            onClick={() => {
              setAccountOpen(false);
              setScenarioOpen(true);
            }}
            disabled={!identity.principal.roles.includes("security_admin")}
          >
            <Activity size={15} />
            Laboratory
          </Button>
          <Button onClick={() => logout.mutate()} busy={logout.isPending}>
            <LogOut size={15} />
            Sign out / switch role
          </Button>
        </div>
      </Modal>
      <ScenarioDialog />
    </div>
  );
}
