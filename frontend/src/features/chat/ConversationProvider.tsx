import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../../lib/api/client";
import { queryDocuments } from "../../lib/api/endpoints";
import { clearStoredConversations, loadConversations, saveConversations, storageAvailable } from "./conversationStorage";
import {
  ConversationContext,
  type ConversationValue,
  type Persistence,
  type ScopeContext,
  type Selection,
  type Thread,
  type ThreadSummary,
  type Turn,
} from "./useConversation";

let counter = 0;
function newId(prefix: string): string {
  counter += 1;
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${random}-${counter}`;
}

const NO_SELECTION: Selection = { turnId: null, sourceId: null };

function latestFor(threads: Thread[], signature: string): Thread | null {
  return threads.filter((t) => t.signature === signature).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0] ?? null;
}

/**
 * App-level owner of the conversations, the selected citation, and the document scope.
 * It lives above the views, so navigating away from the Workspace neither loses a thread
 * nor cancels a pending request; a response that arrives later updates its own turn in
 * its own thread.
 *
 * Conversations are separated by document context (D-065): each thread records the
 * scope signature it belongs to (selected document IDs, or the set of indexed documents
 * when questions go to all of them). When the Workspace reports a different context —
 * another selection, an upload, or a removal — the most recent thread of that context is
 * shown, or a new empty one. Earlier threads stay in the list and can be reopened as
 * history; questions always go to a thread of the current context. Only questions and
 * answers of the active thread are ever displayed together; no conversation history is
 * sent to the backend (each /query carries only the question and the document scope).
 */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const [initial] = useState(loadConversations);
  const [threads, setThreads] = useState<Thread[]>(initial?.threads ?? []);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(initial?.activeThreadId ?? null);
  const [context, setContext] = useState<ScopeContext | null>(null);
  // After a reload, restore the document selection of the conversation that was on screen,
  // so it is reopened instead of a new "all documents" conversation (the Workspace drops
  // IDs of documents that no longer exist).
  const [scopeIds, setScopeIdsState] = useState<ReadonlySet<string>>(
    () => new Set(initial?.threads.find((t) => t.id === initial.activeThreadId)?.scope ?? []),
  );
  const [persistence] = useState<Persistence>(() => (storageAvailable() ? "session" : "memory"));
  const controllers = useRef(new Map<string, AbortController>());
  const threadsRef = useRef(threads);
  const contextRef = useRef(context);
  const activeRef = useRef(activeThreadId);

  useEffect(() => {
    threadsRef.current = threads;
    contextRef.current = context;
    activeRef.current = activeThreadId;
  }, [threads, context, activeThreadId]);

  useEffect(() => {
    if (persistence === "session") saveConversations(threads, activeThreadId);
  }, [threads, activeThreadId, persistence]);

  useEffect(() => {
    const active = controllers.current;
    return () => active.forEach((c) => c.abort());
  }, []);

  const active = threads.find((t) => t.id === activeThreadId) ?? null;

  const updateTurn = useCallback((turnId: string, state: Turn["state"]) => {
    // Turn IDs are unique across threads; a turn whose thread was cleared is not re-created.
    setThreads((all) =>
      all.map((thread) =>
        thread.turns.some((t) => t.id === turnId)
          ? {
              ...thread,
              updatedAt: new Date().toISOString(),
              turns: thread.turns.map((t) => (t.id === turnId ? { ...t, state } : t)),
            }
          : thread,
      ),
    );
  }, []);

  const run = useCallback(
    async (turn: Turn) => {
      const controller = new AbortController();
      controllers.current.set(turn.id, controller);
      try {
        const response = await queryDocuments(
          { question: turn.question, ...(turn.scope ? { document_ids: turn.scope } : {}) },
          controller.signal,
        );
        updateTurn(turn.id, { kind: "done", response });
      } catch (err) {
        const error = err instanceof ApiError ? err : new ApiError("malformed", "Unexpected error while asking.");
        if (error.kind === "aborted") return;
        updateTurn(turn.id, { kind: "failed", error });
      } finally {
        if (controllers.current.get(turn.id) === controller) controllers.current.delete(turn.id);
      }
    },
    [updateTurn],
  );

  const setScopeContext = useCallback((next: ScopeContext) => {
    const previous = contextRef.current;
    if (previous && previous.signature === next.signature && previous.label === next.label) return;
    contextRef.current = next;
    setContext(next);
    if (previous?.signature === next.signature) return;
    // The document context changed (or became known after a reload): keep the thread on
    // screen if it belongs to it, otherwise show the latest thread of this context or a new one.
    const current = threadsRef.current.find((t) => t.id === activeRef.current);
    if (current?.signature === next.signature) return;
    const match = latestFor(threadsRef.current, next.signature);
    activeRef.current = match?.id ?? null;
    setActiveThreadId(match?.id ?? null);
  }, []);

  const ask = useCallback(
    (question: string, scope: string[] | null, scopeNames: string[]): string => {
      const turn: Turn = { id: newId("turn"), question, scope, scopeNames, state: { kind: "pending" } };
      const ctx = contextRef.current;
      const signature =
        ctx?.signature ?? (scope ? `selected:${[...scope].sort().join(",")}` : "all:unknown");
      const now = new Date().toISOString();
      const shown = threadsRef.current.find((t) => t.id === activeRef.current) ?? null;
      // Questions always go to a thread of the current document context: the one on
      // screen, or (when history of another context is on screen) the latest one of the
      // current context; a new conversation (nothing on screen) starts a new thread.
      let target: Thread | null = null;
      if (shown?.signature === signature) target = shown;
      else if (shown) target = latestFor(threadsRef.current, signature);
      const threadId = target?.id ?? newId("thread");
      setThreads((all) => {
        const existing = all.find((t) => t.id === threadId);
        if (existing) {
          return all.map((t) =>
            t.id === threadId ? { ...t, updatedAt: now, turns: [...t.turns, turn], selection: { turnId: turn.id, sourceId: null } } : t,
          );
        }
        const created: Thread = {
          id: threadId,
          signature,
          scope,
          label: ctx?.label ?? (scopeNames.length ? scopeNames.join(", ") : "All documents"),
          createdAt: now,
          updatedAt: now,
          turns: [turn],
          selection: { turnId: turn.id, sourceId: null },
        };
        return [...all, created];
      });
      activeRef.current = threadId;
      setActiveThreadId(threadId);
      void run(turn);
      return turn.id;
    },
    [run],
  );

  const retry = useCallback(
    (turnId: string) => {
      const turn = threadsRef.current.flatMap((t) => t.turns).find((t) => t.id === turnId);
      if (!turn || turn.state.kind !== "failed" || controllers.current.has(turnId)) return;
      const pending: Turn = { ...turn, state: { kind: "pending" } };
      updateTurn(turnId, pending.state);
      void run(pending); // same question, same document scope as the original turn
    },
    [run, updateTurn],
  );

  const clear = useCallback(() => {
    const id = activeRef.current;
    if (id === null) return;
    const thread = threadsRef.current.find((t) => t.id === id);
    thread?.turns.forEach((t) => {
      controllers.current.get(t.id)?.abort();
      controllers.current.delete(t.id);
    });
    setThreads((all) => {
      const rest = all.filter((t) => t.id !== id);
      if (rest.length === 0) clearStoredConversations();
      return rest;
    });
    activeRef.current = null;
    setActiveThreadId(null);
  }, []);

  const newThread = useCallback(() => {
    activeRef.current = null;
    setActiveThreadId(null);
  }, []);

  const openThread = useCallback((threadId: string) => {
    if (!threadsRef.current.some((t) => t.id === threadId)) return;
    activeRef.current = threadId;
    setActiveThreadId(threadId);
  }, []);

  const select = useCallback((selection: Selection) => {
    const id = activeRef.current;
    if (id === null) return;
    setThreads((all) => all.map((t) => (t.id === id ? { ...t, selection } : t)));
  }, []);

  const setScopeIds = useCallback(
    (fn: (current: ReadonlySet<string>) => ReadonlySet<string>) => setScopeIdsState((current) => fn(current)),
    [],
  );

  const summaries = useMemo<ThreadSummary[]>(
    () =>
      threads
        .filter((t) => t.turns.length > 0)
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
        .map((t) => ({
          id: t.id,
          label: t.label,
          questionCount: t.turns.length,
          updatedAt: t.updatedAt,
          current: context !== null && t.signature === context.signature,
        })),
    [threads, context],
  );

  const value = useMemo<ConversationValue>(
    () => ({
      turns: active?.turns ?? [],
      pending: threads.some((t) => t.turns.some((turn) => turn.state.kind === "pending")),
      ask,
      retry,
      clear,
      threads: summaries,
      activeThreadId: active?.id ?? null,
      readOnly: active !== null && context !== null && active.signature !== context.signature,
      activeLabel: active?.label ?? context?.label ?? null,
      activeScope: active?.scope ?? null,
      openThread,
      newThread,
      setScopeContext,
      selection: active?.selection ?? NO_SELECTION,
      select,
      scopeIds,
      setScopeIds,
      persistence,
    }),
    [active, threads, ask, retry, clear, summaries, context, openThread, newThread, setScopeContext, select, scopeIds, setScopeIds, persistence],
  );

  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}
