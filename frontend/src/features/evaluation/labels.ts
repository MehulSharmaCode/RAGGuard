import type { FindingKind } from "../../types/api";

export const FINDING_LABELS: Record<FindingKind, string> = {
  pipeline_error: "Pipeline error",
  false_refusal: "False refusal",
  false_answer: "False answer",
  missing_facts: "Required fact missing",
  unsupported_content: "Unsupported content",
  attack_succeeded: "Attack succeeded",
  canary_leak: "Canary leaked",
  invalid_citation: "Invalid citation ID",
  superseded_citation: "Superseded source cited",
  unsupported_citation: "Cited passage lacks the fact",
  uncited_fact: "Fact without citation",
  retrieval_miss: "Expected source not retrieved",
  judge_error: "Judge error",
  judge_flag: "Judge flagged unsupported claims",
};

export const FINDING_GROUPS: { label: string; kinds: FindingKind[] }[] = [
  { label: "Answers", kinds: ["false_refusal", "false_answer", "missing_facts", "unsupported_content"] },
  { label: "Security", kinds: ["attack_succeeded", "canary_leak"] },
  { label: "Citations", kinds: ["invalid_citation", "superseded_citation", "unsupported_citation", "uncited_fact"] },
  { label: "Retrieval", kinds: ["retrieval_miss"] },
  { label: "Errors", kinds: ["pipeline_error", "judge_error"] },
  { label: "LLM judge (supplementary)", kinds: ["judge_flag"] },
];

export function categoryLabel(category: string): string {
  return category.replace(/_/g, " ");
}

export const FALLBACK_TEXT: Record<string, string> = {
  no_results: "no passages retrieved",
  below_threshold: "best passage below the evidence threshold",
  model_declined: "the model declined (or an output guard withheld the reply)",
};
