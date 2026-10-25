/**
 * Browser-local copy of the conversations in sessionStorage: they survive reloads of this
 * tab and are deleted when the tab closes or the user clears a conversation. Nothing is
 * sent anywhere. Each conversation (thread) records the document context it belongs to
 * (selected document IDs or the indexed corpus) and, per turn, the question, the document
 * scope, and the API response (answer, fallback reason, model, timings, and the excerpts
 * of the passages supplied to the model, needed to reopen citations). Uploaded files and
 * whole documents are never stored. Entries that fail validation are discarded.
 *
 * Format v2 (2026-10-16, D-065) stores threads; a v1 conversation (one global thread) is
 * kept as an "earlier conversation" thread rather than dropped.
 */

import { ApiError, type ApiErrorKind } from "../../lib/api/client";
import { isQueryResponse } from "../../lib/api/guards";
import type { Selection, Thread, Turn } from "./useConversation";

export const STORAGE_KEY = "ragguard.conversation.v2";
export const LEGACY_STORAGE_KEY = "ragguard.conversation.v1";
const VERSION = 2;
export const MAX_STORED_TURNS = 50; // per conversation
export const LEGACY_SIGNATURE = "legacy:v1";
export const LEGACY_LABEL = "Earlier conversation (kept from before conversations were separated by documents)";

const INTERRUPTED =
  "The page was reloaded before the answer arrived, so no answer was recorded. Retry to ask again.";

interface StoredError {
  kind: ApiErrorKind;
  message: string;
  status: number | null;
  code: string | null;
}

type StoredState =
  | { kind: "pending" }
  | { kind: "done"; response: unknown }
  | { kind: "failed"; error: StoredError };

interface StoredTurn {
  id: string;
  question: string;
  scope: string[] | null;
  scopeNames: string[];
  state: StoredState;
}

interface StoredThread {
  id: string;
  signature: string;
  scope: string[] | null;
  label: string;
  createdAt: string;
  updatedAt: string;
  turns: StoredTurn[];
  selection: Selection;
}

interface Stored {
  version: number;
  threads: StoredThread[];
  activeThreadId: string | null;
}

const isStr = (v: unknown): v is string => typeof v === "string";
const isStrArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);

function toStored(turn: Turn): StoredTurn {
  const { state } = turn;
  const stored: StoredState =
    state.kind === "failed"
      ? {
          kind: "failed",
          error: { kind: state.error.kind, message: state.error.message, status: state.error.status, code: state.error.code },
        }
      : state;
  return { id: turn.id, question: turn.question, scope: turn.scope, scopeNames: turn.scopeNames, state: stored };
}

function fromStored(value: unknown): Turn | null {
  if (typeof value !== "object" || value === null) return null;
  const t = value as Partial<StoredTurn>;
  if (!isStr(t.id) || !isStr(t.question) || !isStrArray(t.scopeNames)) return null;
  if (!(t.scope === null || isStrArray(t.scope))) return null;
  const base = { id: t.id, question: t.question, scope: t.scope, scopeNames: t.scopeNames };
  const state = t.state;
  if (!state || typeof state !== "object") return null;
  if (state.kind === "pending") {
    // The request did not survive the reload; record that honestly instead of waiting forever.
    return { ...base, state: { kind: "failed", error: new ApiError("interrupted", INTERRUPTED) } };
  }
  if (state.kind === "done") {
    return isQueryResponse(state.response) ? { ...base, state: { kind: "done", response: state.response } } : null;
  }
  if (state.kind === "failed" && state.error && isStr(state.error.message)) {
    const e = state.error;
    const error = new ApiError(e.kind, e.message, {
      ...(typeof e.status === "number" ? { status: e.status } : {}),
      ...(isStr(e.code) ? { code: e.code } : {}),
    });
    return { ...base, state: { kind: "failed", error } };
  }
  return null;
}

function toSelection(sel: unknown): Selection {
  const v = sel as Partial<Selection> | null | undefined;
  return v && (v.turnId === null || isStr(v.turnId)) && (v.sourceId === null || isStr(v.sourceId))
    ? { turnId: v.turnId ?? null, sourceId: v.sourceId ?? null }
    : { turnId: null, sourceId: null };
}

function fromStoredThread(value: unknown): Thread | null {
  if (typeof value !== "object" || value === null) return null;
  const t = value as Partial<StoredThread>;
  if (!isStr(t.id) || !isStr(t.signature) || !isStr(t.label) || !Array.isArray(t.turns)) return null;
  if (!(t.scope === null || isStrArray(t.scope))) return null;
  const now = new Date().toISOString();
  return {
    id: t.id,
    signature: t.signature,
    scope: t.scope,
    label: t.label,
    createdAt: isStr(t.createdAt) ? t.createdAt : now,
    updatedAt: isStr(t.updatedAt) ? t.updatedAt : now,
    turns: t.turns.map(fromStored).filter((x): x is Turn => x !== null),
    selection: toSelection(t.selection),
  };
}

function readJson(key: string): unknown {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    removeKey(key);
    return null;
  }
}

function removeKey(key: string): void {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Storage blocked: there is nothing stored to remove.
  }
}

/** A v1 conversation (one thread for everything) becomes a thread of its own. */
function loadLegacy(): Thread | null {
  const data = readJson(LEGACY_STORAGE_KEY) as { version?: unknown; turns?: unknown; selection?: unknown } | null;
  if (!data || data.version !== 1 || !Array.isArray(data.turns)) return null;
  const turns = data.turns.map(fromStored).filter((t): t is Turn => t !== null);
  if (turns.length === 0) return null;
  const now = new Date().toISOString();
  return {
    id: "thread-legacy-v1",
    signature: LEGACY_SIGNATURE,
    scope: null,
    label: LEGACY_LABEL,
    createdAt: now,
    updatedAt: now,
    turns,
    selection: toSelection(data.selection),
  };
}

export function loadConversations(): { threads: Thread[]; activeThreadId: string | null } | null {
  const data = readJson(STORAGE_KEY) as Partial<Stored> | null;
  const legacy = loadLegacy();
  if (data && (data.version !== VERSION || !Array.isArray(data.threads))) removeKey(STORAGE_KEY);
  const threads =
    data && data.version === VERSION && Array.isArray(data.threads)
      ? data.threads.map(fromStoredThread).filter((t): t is Thread => t !== null)
      : [];
  if (legacy && !threads.some((t) => t.id === legacy.id)) threads.push(legacy);
  if (threads.length === 0) return null;
  const active = data && isStr(data.activeThreadId) ? data.activeThreadId : null;
  return { threads, activeThreadId: threads.some((t) => t.id === active) ? active : null };
}

/** True when this tab's sessionStorage accepts writes (false in some private modes). */
export function storageAvailable(): boolean {
  try {
    const probe = `${STORAGE_KEY}.probe`;
    window.sessionStorage.setItem(probe, "1");
    window.sessionStorage.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

function toStoredThread(thread: Thread, limit: number): StoredThread {
  return {
    id: thread.id,
    signature: thread.signature,
    scope: thread.scope,
    label: thread.label,
    createdAt: thread.createdAt,
    updatedAt: thread.updatedAt,
    turns: thread.turns.slice(-limit).map(toStored),
    selection: thread.selection,
  };
}

/** Saves every conversation (fewer turns per conversation if the quota is reached). */
export function saveConversations(threads: Thread[], activeThreadId: string | null): boolean {
  const kept = threads.filter((t) => t.turns.length > 0);
  try {
    if (kept.length === 0) {
      window.sessionStorage.removeItem(STORAGE_KEY);
      window.sessionStorage.removeItem(LEGACY_STORAGE_KEY);
      return true;
    }
  } catch {
    return false;
  }
  for (const limit of [MAX_STORED_TURNS, 10]) {
    const stored: Stored = { version: VERSION, threads: kept.map((t) => toStoredThread(t, limit)), activeThreadId };
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
      // The v1 copy has been carried over into a thread; keep only one copy.
      window.sessionStorage.removeItem(LEGACY_STORAGE_KEY);
      return true;
    } catch {
      // Quota reached: retry with fewer turns, then give up (the threads stay in memory).
    }
  }
  return false;
}

export function clearStoredConversations(): void {
  removeKey(STORAGE_KEY);
  removeKey(LEGACY_STORAGE_KEY);
}
