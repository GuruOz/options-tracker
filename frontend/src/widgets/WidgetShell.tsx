/** Card chrome shared by every widget: title, drag handle + edit controls in
 * edit mode, and consistent loading/empty states. Widget bodies render only
 * their content. */
export function WidgetShell({
  title,
  editing,
  onRemove,
  onConfig,
  children,
}: {
  title: string;
  editing: boolean;
  onRemove?: () => void;
  onConfig?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div
        className={`widget-drag flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2 dark:border-slate-800 ${
          editing ? "cursor-move bg-slate-50 dark:bg-slate-800" : ""
        }`}
      >
        <span className="truncate text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
          {title}
        </span>
        {editing && (
          <span className="flex items-center gap-1">
            {onConfig && (
              <button
                onClick={onConfig}
                onMouseDown={(e) => e.stopPropagation()}
                className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-slate-700"
                title="Configure"
              >
                ⚙
              </button>
            )}
            {onRemove && (
              <button
                onClick={onRemove}
                onMouseDown={(e) => e.stopPropagation()}
                className="rounded p-1 text-slate-400 hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-950"
                title="Remove"
              >
                ✕
              </button>
            )}
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
    </div>
  );
}

export function WidgetLoading() {
  return <p className="text-xs text-slate-400 dark:text-slate-500">Loading…</p>;
}

export function WidgetEmpty({ text }: { text: string }) {
  return <p className="text-xs text-slate-400 dark:text-slate-500">{text}</p>;
}
