import type { ReactNode } from "react";

/** A titled region of a data view: hairline rule above, heading, optional actions. */
export function Section({
  id,
  title,
  actions,
  children,
  description,
}: {
  id: string;
  title: string;
  actions?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="border-t border-paper-300 pt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id={id} className="text-16 font-semibold text-ink-900">
            {title}
          </h2>
          {description && <div className="mt-0.5 max-w-[80ch] text-13 text-ink-700">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export const fieldClass =
  "h-8 rounded-sm border border-line-strong bg-paper-50 px-2 text-13 text-ink-900 disabled:text-ink-500";

export function DownloadLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className="inline-flex h-8 items-center gap-1.5 rounded-sm border border-line-strong bg-paper-50 px-2.5 text-13 font-medium text-ink-900 hover:bg-paper-200"
    >
      {children}
    </a>
  );
}
