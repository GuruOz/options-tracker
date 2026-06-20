const PANELS: { title: string; blurb: string }[] = [
  { title: "Premium income", blurb: "Realized P&L (commission-net), win rate, yield, withdrawals." },
  { title: "Flex / CSV import", blurb: "Backfill pre-first-run trade history into executions." },
];

export function PanelGrid() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {PANELS.map((p) => (
        <section
          key={p.title}
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900"
        >
          <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">{p.title}</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{p.blurb}</p>
          <p className="mt-4 inline-block rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            Coming soon
          </p>
        </section>
      ))}
    </div>
  );
}
