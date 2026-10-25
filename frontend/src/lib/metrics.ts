/** Display of MetricValue records from the backend: unavailable is never shown as zero. */

import type { Assessment, MetricValue } from "../types/api";
import { formatMs } from "./format";

export interface MetricText {
  /** Main value, e.g. "90.6%", "4.85", "776 ms", "Not recorded". */
  value: string;
  /** Count context, e.g. "77 / 85", "n = 67"; empty when not applicable. */
  count: string;
  /** Explanation for missing values (tooltip / screen-reader text). */
  note: string | null;
  missing: boolean;
}

export function formatMetric(m: MetricValue): MetricText {
  if (!m.available) {
    return { value: "Not recorded", count: "", note: "This report or run does not record this metric.", missing: true };
  }
  if (m.value === null) {
    const none = m.denominator === 0;
    return {
      value: "n/a",
      count: m.denominator !== null ? `0 applicable` : "",
      note: none ? "No case applied to this metric in this run." : "No value was recorded.",
      missing: true,
    };
  }
  switch (m.kind) {
    case "rate":
      return {
        value: `${(m.value * 100).toFixed(1)}%`,
        count: m.numerator !== null && m.denominator !== null ? `${m.numerator} / ${m.denominator}` : m.denominator !== null ? `of ${m.denominator}` : "",
        note: null,
        missing: false,
      };
    case "mean":
      return { value: m.value.toFixed(2), count: m.denominator !== null ? `n = ${m.denominator}` : "", note: null, missing: false };
    case "ms":
      return { value: formatMs(m.value), count: "", note: null, missing: false };
    default:
      return { value: String(Math.round(m.value)), count: "", note: null, missing: false };
  }
}

export function formatDelta(m: MetricValue, delta: number | null): string {
  if (delta === null) return "—";
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  const abs = Math.abs(delta);
  switch (m.kind) {
    case "rate":
      return `${sign}${(abs * 100).toFixed(1)} pts`;
    case "mean":
      return `${sign}${abs.toFixed(2)}`;
    case "ms":
      return `${sign}${formatMs(abs)}`;
    default:
      return `${sign}${Math.round(abs)}`;
  }
}

export const DIRECTION_TEXT = { higher: "Higher is better", lower: "Lower is better", neutral: "Informational" } as const;

export const ASSESSMENT_TEXT: Record<Assessment, string> = {
  improved: "Improved",
  regressed: "Regressed",
  unchanged: "Unchanged",
  changed: "Changed",
  not_comparable: "Not comparable",
  unavailable: "Unavailable",
};

export function groupBy<T>(items: T[], key: (item: T) => string): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const name = key(item);
    groups.set(name, [...(groups.get(name) ?? []), item]);
  }
  return [...groups.entries()];
}

export function shortHash(value: string | null | undefined, length = 12): string {
  return value ? value.slice(0, length) : "—";
}
