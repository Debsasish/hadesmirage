import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, ApiError, post, setCsrf } from "./api";
import type { Me, Origin, Overview } from "./types";

type Notice = { message: string; kind: "success" | "error"; id: number } | null;
interface WorkspaceState {
  theme: "dark" | "light";
  setTheme: (value: "dark" | "light") => void;
  hours: 1 | 24 | 168;
  setHours: (value: 1 | 24 | 168) => void;
  origin: Origin;
  setOrigin: (value: Origin) => void;
  notice: Notice;
  notify: (message: string, kind?: "success" | "error") => void;
  dismiss: () => void;
  scenarioOpen: boolean;
  setScenarioOpen: (value: boolean) => void;
  sidebarCompact: boolean;
  setSidebarCompact: (value: boolean) => void;
  autoRefresh: boolean;
  setAutoRefresh: (value: boolean) => void;
  translucent: boolean;
  setTranslucent: (value: boolean) => void;
}
const Workspace = createContext<WorkspaceState | null>(null);
function savedTheme(): "dark" | "light" {
  return localStorage.getItem("mirage.theme") === "light" ? "light" : "dark";
}
function savedTransparency() {
  const saved = localStorage.getItem("mirage.transparency");
  if (saved === "solid") return false;
  if (saved === "glass") return true;
  return !window.matchMedia("(prefers-reduced-transparency: reduce)").matches;
}
export function initializeAppearance() {
  document.documentElement.dataset.theme = savedTheme();
  document.documentElement.dataset.transparency = savedTransparency() ? "glass" : "solid";
}
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState(savedTheme);
  const [hours, setHours] = useState<1 | 24 | 168>(24);
  const [origin, setOrigin] = useState<Origin>("all");
  const [notice, setNotice] = useState<Notice>(null);
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [sidebarCompact, setSidebarCompact] = useState(
    () => localStorage.getItem("mirage.sidebarCompact") === "true",
  );
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [translucent, setTranslucent] = useState(savedTransparency);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("mirage.theme", theme);
  }, [theme]);
  useEffect(() => {
    localStorage.setItem("mirage.sidebarCompact", String(sidebarCompact));
  }, [sidebarCompact]);
  useEffect(() => {
    const value = translucent ? "glass" : "solid";
    document.documentElement.dataset.transparency = value;
    localStorage.setItem("mirage.transparency", value);
  }, [translucent]);
  useEffect(() => {
    if (!notice) return;
    const timeout = setTimeout(() => setNotice(null), notice.kind === "error" ? 12000 : 5000);
    return () => clearTimeout(timeout);
  }, [notice]);
  return (
    <Workspace.Provider
      value={{
        theme,
        setTheme,
        hours,
        setHours,
        origin,
        setOrigin,
        notice,
        notify: (message, kind = "success") => setNotice({ message, kind, id: Date.now() }),
        dismiss: () => setNotice(null),
        scenarioOpen,
        setScenarioOpen,
        sidebarCompact,
        setSidebarCompact,
        autoRefresh,
        setAutoRefresh,
        translucent,
        setTranslucent,
      }}
    >
      {children}
    </Workspace.Provider>
  );
}
export function useWorkspace() {
  const value = useContext(Workspace);
  if (!value) throw new Error("Workspace provider is missing");
  return value;
}
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const result = await api<Me>("/auth/me");
      setCsrf(result.csrf);
      return result;
    },
    staleTime: 60_000,
    retry: false,
  });
}
export function useOverview() {
  const { hours, origin, autoRefresh } = useWorkspace();
  return useQuery({
    queryKey: ["overview", hours, origin],
    queryFn: () => api<Overview>(`/v1/overview?hours=${hours}&origin=${origin}`),
    refetchInterval: autoRefresh ? 20_000 : false,
    refetchOnWindowFocus: autoRefresh,
    refetchOnReconnect: autoRefresh,
  });
}
export function useAction<T, V = void>(perform: (value: V) => Promise<T>, message?: string) {
  const client = useQueryClient();
  const { notify } = useWorkspace();
  return useMutation({
    mutationFn: perform,
    onSuccess: () => {
      void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "me" });
      if (message) notify(message);
    },
    onError: (error) =>
      notify(error instanceof Error ? error.message : "The operation failed", "error"),
  });
}
export function useLogout() {
  const client = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: () => post<{ iap_sign_out_url?: string }>("/auth/logout"),
    onSuccess: (result) => {
      setCsrf(null);
      client.clear();
      if (result?.iap_sign_out_url) {
        window.location.assign(result.iap_sign_out_url);
        return;
      }
      navigate("/login", { replace: true });
    },
  });
}
export function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 403)
    return "Permission denied. Your verified role cannot access this operation.";
  return error instanceof Error ? error.message : "The requested data could not be loaded.";
}
export function useFilters<T extends Record<string, string>>(
  key: string,
  initial: T,
  overrides: Partial<T> = {},
) {
  const [value, setValue] = useState<T>(() => {
    const merge = (candidate: T): T => ({ ...candidate, ...overrides });
    const raw = localStorage.getItem(`mirage.filters.${key}`);
    if (!raw) return merge(initial);
    try {
      const parsed: unknown = JSON.parse(raw);
      if (typeof parsed !== "object" || parsed === null) return merge(initial);
      const values = { ...initial };
      for (const name of Object.keys(initial)) {
        if (name in parsed && typeof Reflect.get(parsed, name) === "string")
          Reflect.set(values, name, Reflect.get(parsed, name));
      }
      return merge(values);
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      localStorage.removeItem(`mirage.filters.${key}`);
      return merge(initial);
    }
  });
  useEffect(
    () => localStorage.setItem(`mirage.filters.${key}`, JSON.stringify(value)),
    [key, value],
  );
  return [value, setValue] as const;
}
