import { CircleCheck, CircleDashed, CircleX, LoaderCircle, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

export type Tone = "pass" | "fail" | "warn" | "pending" | "loading";

const ICONS = {
  pass: CircleCheck,
  fail: CircleX,
  warn: TriangleAlert,
  pending: CircleDashed,
  loading: LoaderCircle,
} as const;

const TEXT: Record<Tone, string> = {
  pass: "text-pass",
  fail: "text-fail",
  warn: "text-warn",
  pending: "text-ink-500",
  loading: "text-ink-500",
};

/** Status is always icon + text label + colour, never colour alone (§3.2). */
export function StatusTag({
  tone,
  children,
  className = "",
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
}) {
  const Icon = ICONS[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-13 font-medium ${TEXT[tone]} ${className}`}
    >
      <Icon
        aria-hidden="true"
        size={14}
        strokeWidth={1.75}
        className={tone === "loading" ? "shrink-0 animate-spin" : "shrink-0"}
      />
      <span className="text-ink-700">{children}</span>
    </span>
  );
}
