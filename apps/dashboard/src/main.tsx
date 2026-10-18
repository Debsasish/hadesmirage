import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/inter";
import "./styles.css";
import "./console.css";
import "./wiz.css";
import "./attack-map.css";
import { ApiError } from "./api";
import { Button, Empty, Toast } from "./components";
import { ExperienceProvider } from "./experience";
import { Shell } from "./shell";
import { initializeAppearance, WorkspaceProvider } from "./state";
import { LoginPage } from "./pages/login";
import { OverviewPage } from "./pages/overview";
import { IncidentPage, IncidentsPage } from "./pages/incidents";
import { AgentsPage } from "./pages/agents";
import { GuardrailsPage } from "./pages/guardrails";
import { DeceptionPage } from "./pages/deception";
import { ArchitecturePage } from "./pages/architecture";
import { IntegrationsPage } from "./pages/integrations";
import { AuditPage } from "./pages/audit";
import { SettingsPage } from "./pages/settings";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: (count, error) =>
        count < 1 && !(error instanceof ApiError && [401, 403, 404].includes(error.status)),
    },
    mutations: { retry: false },
  },
});

initializeAppearance();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ExperienceProvider>
        <WorkspaceProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route element={<Shell />}>
                <Route index element={<Navigate to="/overview" replace />} />
                <Route path="/overview" element={<OverviewPage />} />
                <Route path="/incidents" element={<IncidentsPage />} />
                <Route path="/incidents/:id" element={<IncidentPage />} />
                <Route path="/agents" element={<AgentsPage />} />
                <Route path="/guardrails" element={<GuardrailsPage />} />
                <Route path="/deception" element={<DeceptionPage />} />
                <Route path="/architecture" element={<ArchitecturePage />} />
                <Route path="/integrations" element={<IntegrationsPage />} />
                <Route path="/audit" element={<AuditPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route
                  path="*"
                  element={
                    <div className="page">
                      <Empty
                        title="This view does not exist"
                        action={
                          <Button onClick={() => window.location.assign("/overview")}>
                            Return to overview
                          </Button>
                        }
                      />
                    </div>
                  }
                />
              </Route>
            </Routes>
            <Toast />
          </BrowserRouter>
        </WorkspaceProvider>
      </ExperienceProvider>
    </QueryClientProvider>
  </StrictMode>,
);
