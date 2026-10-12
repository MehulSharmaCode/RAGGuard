import { CircleX, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

type Tone = "error" | "warning" | "info";

const STYLE: Record<Tone, { icon: typeof CircleX; rule: string; iconColor: string }> = {
  error: { icon: CircleX, rule: "border-l-fail", iconColor: "text-fail" },
  warning: { icon: TriangleAlert, rule: "border-l-warn", iconColor: "text-warn" },
  info: { icon: Info, rule: "border-l-ink-500", iconColor: "text-ink-500" },
};

/** Region-bound message. Errors use role="alert"; others are polite status updates. */
export function InlineAlert({
  tone,
  title,
  children,
  action,
  className = "",
}: {
  tone: Tone;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const { icon: Icon, rule, iconColor } = STYLE[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`flex gap-3 rounded-sm border border-paper-300 border-l-2 ${rule} bg-paper-50 px-3 py-2.5 ${className}`}
    >
      <Icon aria-hidden="true" size={16} strokeWidth={1.75} className={`mt-0.5 shrink-0 ${iconColor}`} />
      <div className="min-w-0 flex-1">
        <p className="text-14 font-medium text-ink-900">{title}</p>
        {children && <div className="mt-0.5 text-13 text-ink-700">{children}</div>}
        {action && <div className="mt-2">{action}</div>}
      </div>
    </div>
  );
}
