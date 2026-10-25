import { groupBy, DIRECTION_TEXT, formatMetric } from "../../lib/metrics";
import type { MetricValue } from "../../types/api";

/** Aligned metric rows (UI_DESIGN_SPEC §7 "Metric row"), grouped, not a grid of KPI cards. */
export function MetricLedger({ metrics, judgeNote }: { metrics: MetricValue[]; judgeNote?: string }) {
  return (
    <div className="space-y-5">
      {groupBy(metrics, (m) => m.group).map(([group, rows]) => (
        <div key={group}>
          <h3 className="section-label mb-1">{group}</h3>
          {rows[0]?.supplementary && judgeNote && <p className="mb-1 text-12 text-ink-500">{judgeNote}</p>}
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[480px] border-collapse text-13">
              <thead className="sr-only">
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col">Value</th>
                  <th scope="col">Cases</th>
                  <th scope="col">Direction</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => {
                  const text = formatMetric(m);
                  return (
                    <tr key={m.key} className="border-b border-paper-300 last:border-b-0">
                      <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink-900">
                        {m.label}
                      </th>
                      <td
                        className={`tnum w-28 py-1.5 pr-3 text-right font-mono ${text.missing ? "text-ink-500" : "text-ink-900"}`}
                        title={text.note ?? undefined}
                      >
                        {text.value}
                        {text.note && <span className="sr-only"> — {text.note}</span>}
                      </td>
                      <td className="tnum w-24 py-1.5 pr-3 text-right font-mono text-12 text-ink-500">{text.count}</td>
                      <td className="w-36 py-1.5 text-right text-12 text-ink-500">{DIRECTION_TEXT[m.direction]}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
