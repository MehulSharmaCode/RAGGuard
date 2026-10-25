import { createContext, useContext } from "react";
import type { ApiError } from "../../lib/api/client";
import type { QueryResponse } from "../../types/api";

export type TurnState =
  | { kind: "pending" }
  | { kind: "done"; response: QueryResponse }
  | { kind: "failed"; error: ApiError };

export interface Turn {
  id: string;
  question: string;
  /** Document IDs the question was limited to; null means all indexed documents. */
  scope: string[] | null;
  scopeNames: string[];
  state: TurnState;
}

export interface Selection {
  turnId: string | null;
  sourceId: string | null;
}

/** Where the conversation is kept: this tab's session storage, or memory only (storage blocked). */
export type Persistence = "session" | "memory";

/**
 * The document context a conversation belongs to. `signature` is stable for the same
 * context: the selected document IDs, or, when questions go to all documents, the IDs of
 * every indexed document (so an upload or a removal is a different context).
 */
export interface ScopeContext {
  signature: string;
  /** Selected document IDs, or null for all indexed documents. */
  scope: string[] | null;
  /** Human-readable description, e.g. "All documents: a.pdf, b.txt". */
  label: string;
}

export interface Thread {
  id: string;
  signature: string;
  scope: string[] | null;
  label: string;
  createdAt: string;
  updatedAt: string;
  turns: Turn[];
  selection: Selection;
}

export interface ThreadSummary {
  id: string;
  label: string;
  questionCount: number;
  updatedAt: string;
  /** True when the thread belongs to the current document context. */
  current: boolean;
}

export interface ConversationValue {
  /** Turns of the conversation on screen. */
  turns: Turn[];
  /** True while any conversation (not only the one on screen) waits for an answer. */
  pending: boolean;
  ask: (question: string, scope: string[] | null, scopeNames: string[]) => string;
  retry: (turnId: string) => void;
  /** Deletes the conversation on screen (other conversations are kept). */
  clear: () => void;
  /** All conversations of this tab, newest first. */
  threads: ThreadSummary[];
  /** The conversation on screen; null is a new, still empty conversation. */
  activeThreadId: string | null;
  /** The conversation on screen belongs to another document context (history view). */
  readOnly: boolean;
  /** Description of the documents the conversation on screen was held with. */
  activeLabel: string | null;
  /** Scope of the conversation on screen (to restore it), or null. */
  activeScope: string[] | null;
  openThread: (threadId: string) => void;
  /** Starts an empty conversation for the current document context. */
  newThread: () => void;
  /** Reported by the Workspace whenever the effective document context may have changed. */
  setScopeContext: (context: ScopeContext) => void;
  selection: Selection;
  select: (selection: Selection) => void;
  scopeIds: ReadonlySet<string>;
  setScopeIds: (update: (current: ReadonlySet<string>) => ReadonlySet<string>) => void;
  persistence: Persistence;
}

export const ConversationContext = createContext<ConversationValue | null>(null);

/** The app-level conversations (ConversationProvider): survive navigation between views. */
export function useConversation(): ConversationValue {
  const value = useContext(ConversationContext);
  if (value === null) throw new Error("useConversation must be used inside <ConversationProvider>.");
  return value;
}
