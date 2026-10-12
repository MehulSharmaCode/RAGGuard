import { CornerDownLeft } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";
import { Button } from "../../components/ui/Button";

const MAX_LENGTH = 2000; // QueryRequest.question max_length in the backend schema

export interface QuestionInputProps {
  onAsk: (question: string) => void;
  disabledReason: string | null;
  busy: boolean;
  scopeLabel: string;
  onClearScope: (() => void) | null;
}

export function QuestionInput({ onAsk, disabledReason, busy, scopeLabel, onClearScope }: QuestionInputProps) {
  const [value, setValue] = useState("");
  const question = value.trim();
  const blocked = disabledReason !== null || busy;
  const canSubmit = !blocked && question.length > 0 && value.length <= MAX_LENGTH;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSubmit) return;
    onAsk(question);
    setValue("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="space-y-2" aria-label="Ask a question">
      <div className="flex items-center justify-between gap-2 text-12 text-ink-500">
        <span className="truncate">
          Scope: <span className="text-ink-700">{scopeLabel}</span>
        </span>
        {onClearScope && (
          <button type="button" onClick={onClearScope} className="shrink-0 rounded-xs text-ink-700 underline underline-offset-2 hover:text-ink-900">
            Use all documents
          </button>
        )}
      </div>
      <div className="flex items-end gap-2">
        <label htmlFor="question" className="sr-only">Question</label>
        <textarea
          id="question"
          rows={2}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={disabledReason ?? "Ask about your documents…"}
          aria-describedby="question-hint"
          className="max-h-40 min-h-[56px] flex-1 resize-y rounded-sm border border-line-strong bg-paper-50 px-3 py-2 text-14 text-ink-900 placeholder:text-ink-500 disabled:cursor-not-allowed disabled:bg-paper-200"
          disabled={disabledReason !== null}
        />
        <Button type="submit" variant="primary" icon={CornerDownLeft} disabled={!canSubmit} loading={busy}>
          Ask
        </Button>
      </div>
      <p id="question-hint" className="tnum text-12 text-ink-500">
        {busy
          ? "Waiting for the current answer…"
          : value.length > MAX_LENGTH
            ? `${value.length} / ${MAX_LENGTH} characters — shorten the question.`
            : "Enter to ask · Shift+Enter for a new line"}
      </p>
    </form>
  );
}
