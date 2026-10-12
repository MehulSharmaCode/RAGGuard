/**
 * Document Workspace (UI_DESIGN_SPEC §8.2): documents | conversation | evidence.
 * ≥ xl: three columns. lg: two columns with evidence as a side sheet.
 * < lg: one column with section switcher (Documents · Ask · Evidence).
 */

import { RotateCw, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../components/ui/Button";
import { InlineAlert } from "../components/ui/InlineAlert";
import { EvidencePanel } from "../features/chat/EvidencePanel";
import { QuestionInput } from "../features/chat/QuestionInput";
import { EvidenceTrace } from "../features/chat/trace/EvidenceTrace";
import { FirstRunIllustration } from "../features/chat/trace/FirstRunIllustration";
import { TurnView } from "../features/chat/TurnView";
import { useConversation } from "../features/chat/useConversation";
import { DocumentList } from "../features/documents/DocumentList";
import { UploadZone } from "../features/documents/UploadZone";
import { useDocuments, useUpload } from "../features/documents/useDocuments";
import { useMediaQuery } from "../lib/browser";
import { plural } from "../lib/format";
import { maxUploadMb, type HealthState } from "./useHealth";

type Section = "documents" | "ask" | "evidence";
const SECTIONS: { id: Section; label: string }[] = [
  { id: "documents", label: "Documents" },
  { id: "ask", label: "Ask" },
  { id: "evidence", label: "Evidence" },
];

export function Workspace({ health }: { health: HealthState }) {
  const docs = useDocuments();
  const conversation = useConversation();
  const isXl = useMediaQuery("(min-width: 1280px)");
  const isLg = useMediaQuery("(min-width: 1024px)");

  const [section, setSection] = useState<Section>("ask");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [scopeIds, setScopeIds] = useState<ReadonlySet<string>>(new Set());
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [traceTurnId, setTraceTurnId] = useState<string | null>(null);
  const pickerRef = useRef<HTMLInputElement>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);

  const limitMb = maxUploadMb(health);
  const { refresh: refreshDocs } = docs;
  const onIndexed = useCallback(() => void refreshDocs(), [refreshDocs]);
  const uploader = useUpload(limitMb !== null ? limitMb * 1024 * 1024 : null, onIndexed);

  const backendDown = health.error !== null;
  const generationDown = !backendDown && health.data !== null && !health.data.generation_ready;
  const documents = docs.documents;
  const noDocuments = documents !== null && documents.length === 0;

  // Scope only ever contains documents that still exist on the server.
  const scope = useMemo(() => {
    const live = new Set((documents ?? []).map((d) => d.document_id));
    return new Set([...scopeIds].filter((id) => live.has(id)));
  }, [scopeIds, documents]);
  const scopeNames = (documents ?? []).filter((d) => scope.has(d.document_id)).map((d) => d.filename);

  const toggleScope = (id: string) =>
    setScopeIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const showEvidence = () => {
    if (isXl) return;
    if (isLg) setSheetOpen(true);
    else setSection("evidence");
  };

  const selectSource = (turnId: string, sourceId: string) => {
    setSelectedTurnId(turnId);
    setSelectedSourceId(sourceId);
    showEvidence();
  };

  const ask = (question: string) => {
    const id = conversation.ask(question, scope.size ? [...scope] : null, scopeNames);
    setSelectedTurnId(id);
    setSelectedSourceId(null);
  };

  useEffect(() => {
    threadEndRef.current?.scrollIntoView?.({ block: "end" });
  }, [conversation.turns.length]);

  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setSheetOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sheetOpen]);

  const selectedTurn = conversation.turns.find((t) => t.id === selectedTurnId) ?? null;

  const uploadDisabledReason = backendDown ? "Uploads are unavailable while the backend is unreachable." : null;
  const questionDisabledReason = backendDown
    ? "The backend is unreachable."
    : noDocuments
      ? "Upload a document to ask questions."
      : null;

  const scopeLabel = scope.size
    ? `${plural(scope.size, "selected document")}`
    : documents
      ? `all documents (${documents.length})`
      : "all documents";

  const openPicker = () => {
    setSection("documents");
    pickerRef.current?.click();
  };

  const visible = (id: Section) => (section === id ? "flex" : "hidden");
  const evidenceClass = `${visible("evidence")} ${
    sheetOpen ? "lg:fixed lg:inset-y-0 lg:right-0 lg:z-30 lg:flex lg:w-[380px] lg:shadow-raised" : "lg:hidden"
  } xl:static xl:z-auto xl:flex xl:w-auto xl:shadow-none`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <nav aria-label="Workspace sections" className="flex border-b border-paper-300 bg-paper-50 lg:hidden">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            aria-current={section === s.id ? "true" : undefined}
            onClick={() => setSection(s.id)}
            className={`flex-1 border-b-2 py-2.5 text-14 ${
              section === s.id ? "border-b-ink-900 font-medium text-ink-900" : "border-b-transparent text-ink-700"
            }`}
          >
            {s.label}
            {s.id === "documents" && documents && <span className="tnum ml-1 font-mono text-12 text-ink-500">{documents.length}</span>}
          </button>
        ))}
      </nav>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)_380px]">
        <aside aria-label="Documents" className={`${visible("documents")} min-h-0 flex-col border-paper-300 bg-paper-100 lg:flex lg:border-r`}>
          <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
            <UploadZone
              state={uploader.state}
              onFile={(file) => void uploader.upload(file)}
              onDismiss={uploader.reset}
              maxUploadMb={limitMb}
              disabledReason={uploadDisabledReason}
              inputRef={pickerRef}
            />
            <div>
              <div className="flex items-center justify-between">
                <h2 className="section-label">
                  Documents{documents && <span className="tnum"> · {documents.length}</span>}
                </h2>
                <button
                  type="button"
                  onClick={() => void docs.refresh()}
                  aria-label="Reload document list"
                  title="Reload document list"
                  className="rounded-sm p-1 text-ink-500 hover:bg-paper-200 hover:text-ink-900"
                >
                  <RotateCw aria-hidden="true" size={14} strokeWidth={1.75} className={docs.loading ? "animate-spin" : undefined} />
                </button>
              </div>
              {documents && documents.length > 0 && (
                <p className="mt-1 text-12 text-ink-500">Tick documents to limit questions to them.</p>
              )}
              <div className="mt-1">
                <DocumentList
                  documents={documents}
                  loading={docs.loading}
                  error={docs.error}
                  onRetry={() => void docs.refresh()}
                  onRemove={docs.remove}
                  scope={scope}
                  onToggleScope={toggleScope}
                />
              </div>
            </div>
          </div>
        </aside>

        <section aria-label="Conversation" className={`${visible("ask")} min-h-0 flex-col lg:flex`}>
          <div className="flex-1 overflow-y-auto px-4 py-5 md:px-8">
            <div className="mx-auto max-w-[760px] space-y-6">
              {backendDown && (
                <InlineAlert
                  tone="error"
                  title="The backend is unreachable"
                  action={
                    <Button size="sm" icon={RotateCw} loading={health.loading} onClick={() => { void health.refresh(); void docs.refresh(); }}>
                      Retry
                    </Button>
                  }
                >
                  {health.error?.message} Uploads and questions are disabled until it responds.
                </InlineAlert>
              )}
              {generationDown && (
                <InlineAlert tone="warning" title="Answer generation is unavailable">
                  {health.data?.components.generation?.detail} Questions that pass the evidence check will fail
                  until the model is available; questions without enough evidence still return the fallback.
                </InlineAlert>
              )}

              {noDocuments && conversation.turns.length === 0 && (
                <div className="space-y-5 pt-2">
                  <div>
                    <h2 className="text-18 font-semibold text-ink-900">No documents indexed</h2>
                    <p className="mt-1 max-w-[60ch] text-14 text-ink-700">
                      Upload a PDF or TXT file — every answer will cite the passage and page it came from, and
                      when the documents don&apos;t contain enough evidence, RAGGuard says so instead of guessing.
                    </p>
                    <Button className="mt-3" variant="primary" icon={Upload} onClick={openPicker} disabled={backendDown}>
                      Upload a document
                    </Button>
                  </div>
                  <FirstRunIllustration />
                </div>
              )}

              {!noDocuments && documents !== null && conversation.turns.length === 0 && (
                <div className="pt-2">
                  <h2 className="text-18 font-semibold text-ink-900">Ask about your documents</h2>
                  <p className="mt-1 max-w-[60ch] text-14 text-ink-700">
                    Answers cite the passages they rely on. Select a citation to read the passage, or use
                    “Trace this answer” to see how evidence flowed from your documents to the answer.
                  </p>
                </div>
              )}

              {documents === null && docs.loading && !backendDown && conversation.turns.length === 0 && (
                <p className="text-13 text-ink-500" aria-busy="true">Loading workspace…</p>
              )}

              {conversation.turns.map((turn) => (
                <TurnView
                  key={turn.id}
                  turn={turn}
                  selected={turn.id === selectedTurnId}
                  selectedSourceId={turn.id === selectedTurnId ? selectedSourceId : null}
                  traceOpen={traceTurnId === turn.id}
                  onCite={(sourceId) => selectSource(turn.id, sourceId)}
                  onShowEvidence={() => {
                    setSelectedTurnId(turn.id);
                    showEvidence();
                  }}
                  onToggleTrace={() => {
                    setSelectedTurnId(turn.id);
                    setTraceTurnId(traceTurnId === turn.id ? null : turn.id);
                  }}
                  onRetry={() => conversation.retry(turn.id)}
                  trace={
                    turn.state.kind === "done" ? (
                      <EvidenceTrace
                        response={turn.state.response}
                        documents={documents}
                        selectedSourceId={turn.id === selectedTurnId ? selectedSourceId : null}
                        onSelectSource={(sourceId) => {
                          setSelectedTurnId(turn.id);
                          setSelectedSourceId(sourceId);
                        }}
                      />
                    ) : null
                  }
                />
              ))}
              <div ref={threadEndRef} />
            </div>
          </div>
          <div className="border-t border-paper-300 bg-paper-50 px-4 py-3 md:px-8">
            <div className="mx-auto max-w-[760px]">
              <QuestionInput
                onAsk={ask}
                busy={conversation.pending}
                disabledReason={questionDisabledReason}
                scopeLabel={scopeLabel}
                onClearScope={scope.size ? () => setScopeIds(new Set()) : null}
              />
            </div>
          </div>
        </section>

        <aside aria-label="Evidence" className={`${evidenceClass} min-h-0 flex-col border-paper-300 bg-paper-100 xl:border-l`}>
          <EvidencePanel
            turn={selectedTurn}
            selectedSourceId={selectedSourceId}
            onSelectSource={(id) => setSelectedSourceId(id)}
            onClose={sheetOpen && isLg && !isXl ? () => setSheetOpen(false) : undefined}
          />
        </aside>
      </div>
    </div>
  );
}
