import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api/client";
import { queryDocuments } from "../../lib/api/endpoints";
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

let nextId = 0;

/** In-memory question/answer thread for this browser session (not persisted). */
export function useConversation() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const controllers = useRef(new Set<AbortController>());

  useEffect(() => {
    const active = controllers.current;
    return () => active.forEach((c) => c.abort());
  }, []);

  const run = useCallback(async (turn: Turn) => {
    const controller = new AbortController();
    controllers.current.add(controller);
    try {
      const response = await queryDocuments(
        { question: turn.question, ...(turn.scope ? { document_ids: turn.scope } : {}) },
        controller.signal,
      );
      setTurns((all) => all.map((t) => (t.id === turn.id ? { ...t, state: { kind: "done", response } } : t)));
    } catch (err) {
      const error =
        err instanceof ApiError ? err : new ApiError("malformed", "Unexpected error while asking.");
      if (error.kind === "aborted") return;
      setTurns((all) => all.map((t) => (t.id === turn.id ? { ...t, state: { kind: "failed", error } } : t)));
    } finally {
      controllers.current.delete(controller);
    }
  }, []);

  const ask = useCallback(
    (question: string, scope: string[] | null, scopeNames: string[]): string => {
      const turn: Turn = {
        id: `turn-${++nextId}`,
        question,
        scope,
        scopeNames,
        state: { kind: "pending" },
      };
      setTurns((all) => [...all, turn]);
      void run(turn);
      return turn.id;
    },
    [run],
  );

  const retry = useCallback(
    (turnId: string) => {
      const turn = turns.find((t) => t.id === turnId);
      if (!turn || turn.state.kind !== "failed") return;
      const pending: Turn = { ...turn, state: { kind: "pending" } };
      setTurns((all) => all.map((t) => (t.id === turnId ? pending : t)));
      void run(pending);
    },
    [turns, run],
  );

  const pending = turns.some((t) => t.state.kind === "pending");
  return { turns, ask, retry, pending };
}
