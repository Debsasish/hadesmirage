import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Lens = "plain" | "technical";

interface ChatRequest {
  caseId?: string;
  caseNumber?: string;
  caseVersion?: number;
  question?: string;
  autoSend?: boolean;
}

interface ExperienceState {
  lens: Lens;
  setLens: (value: Lens) => void;
  chat: ChatRequest | null;
  chatOpen: boolean;
  openChat: (request?: ChatRequest) => void;
  closeChat: () => void;
}

const ExperienceContext = createContext<ExperienceState | null>(null);

function storedLens(): Lens {
  try {
    return localStorage.getItem("mirage.lens") === "technical" ? "technical" : "plain";
  } catch {
    return "plain";
  }
}

export function ExperienceProvider({ children }: { children: ReactNode }) {
  const [lens, setLensState] = useState<Lens>(storedLens);
  const [chat, setChat] = useState<ChatRequest | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const setLens = useCallback((value: Lens) => {
    setLensState(value);
    try {
      localStorage.setItem("mirage.lens", value);
    } catch {
      // Preference persistence is optional.
    }
  }, []);
  const value = useMemo(
    () => ({
      lens,
      setLens,
      chat,
      chatOpen,
      openChat: (request: ChatRequest = {}) => {
        setChat({ ...request });
        setChatOpen(true);
      },
      closeChat: () => setChatOpen(false),
    }),
    [lens, setLens, chat, chatOpen],
  );
  return <ExperienceContext.Provider value={value}>{children}</ExperienceContext.Provider>;
}

export function useExperience() {
  const value = useContext(ExperienceContext);
  if (!value) throw new Error("Experience context is unavailable");
  return value;
}

export function useLens() {
  const { lens, setLens } = useExperience();
  return { lens, setLens, plain: lens === "plain" };
}

const plainStatus: Record<string, string> = {
  PRODUCTION: "Normal access",
  RESTRICTED: "Access limited",
  DECOY_PENDING: "Moving to honeypot",
  DECOY: "In honeypot",
  TERMINATED: "Disconnected",
  deny: "Blocked",
  allow: "Allowed",
  simulated: "Fake response",
  observed: "Seen",
  require_approval: "Needs approval",
  success: "Done",
  failure: "Failed",
  ACTIVE: "Running",
  DESTROYED: "Removed",
};

export function plainLabel(value: string) {
  return plainStatus[value];
}

export const plainRules: Record<string, string> = {
  "D-001": "Many blocked requests",
  "D-002": "Probing + forbidden action",
  "D-003": "Tampered approval",
  "D-004": "Tried to gain more power",
  "D-005": "Touched honeypot bait",
  "D-006": "Hidden instructions + forbidden action",
};

export function LensToggle({ compact = false }: { compact?: boolean }) {
  const { lens, setLens } = useLens();
  return (
    <div
      className={`lens-toggle ${compact ? "compact" : ""}`}
      role="group"
      aria-label="Detail level"
    >
      <button
        type="button"
        aria-pressed={lens === "plain"}
        className={lens === "plain" ? "active" : ""}
        onClick={() => setLens("plain")}
      >
        Plain view
      </button>
      <button
        type="button"
        aria-pressed={lens === "technical"}
        className={lens === "technical" ? "active" : ""}
        onClick={() => setLens("technical")}
      >
        Technical view
      </button>
    </div>
  );
}
