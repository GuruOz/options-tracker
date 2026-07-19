import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import GridLayout, { WidthProvider, type Layout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { getJSON, putJSON } from "../api/client";
import { useScope } from "../hooks/useScope";
import {
  WIDGETS,
  type WidgetItem,
  defaultLayout,
  newItem,
  toGridLayout,
} from "../widgets/registry";
import { WidgetShell } from "../widgets/WidgetShell";

const Grid = WidthProvider(GridLayout);

interface StoredLayout {
  scope: string;
  layout: { items: WidgetItem[] } | null;
}

export function HomePage() {
  const { selected } = useScope();
  const [editing, setEditing] = useState(false);
  const [items, setItems] = useState<WidgetItem[]>([]);
  const [adding, setAdding] = useState(false);
  const [configuring, setConfiguring] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", "layout", selected],
    queryFn: () =>
      getJSON<StoredLayout>(`/api/dashboard/layout?scope=${encodeURIComponent(selected)}`),
  });

  // Load saved layout (or the default) whenever the scope changes.
  useEffect(() => {
    if (data === undefined) return;
    const saved = data.layout?.items;
    setItems(saved && saved.length ? saved : defaultLayout());
  }, [data, selected]);

  const persist = (next: WidgetItem[]) => {
    setItems(next);
    void putJSON(`/api/dashboard/layout?scope=${encodeURIComponent(selected)}`, {
      layout: { items: next },
    }).catch(() => {});
  };

  const applyPositions = (layout: Layout[]) => {
    const pos = new Map(layout.map((l) => [l.i, l]));
    setItems((prev) =>
      prev.map((it) => {
        const l = pos.get(it.i);
        return l ? { ...it, x: l.x, y: l.y, w: l.w, h: l.h } : it;
      }),
    );
  };

  const savePositions = (layout: Layout[]) => {
    const pos = new Map(layout.map((l) => [l.i, l]));
    persist(items.map((it) => {
      const l = pos.get(it.i);
      return l ? { ...it, x: l.x, y: l.y, w: l.w, h: l.h } : it;
    }));
  };

  const addWidget = (type: string) => {
    const maxY = items.reduce((m, it) => Math.max(m, it.y + it.h), 0);
    persist([...items, { ...newItem(type), x: 0, y: maxY }]);
    setAdding(false);
  };
  const removeWidget = (i: string) => persist(items.filter((it) => it.i !== i));
  const setConfig = (i: string, config: Record<string, unknown>) =>
    persist(items.map((it) => (it.i === i ? { ...it, config } : it)));

  const gridLayout = useMemo(() => toGridLayout(items), [items]);

  if (isLoading) {
    return <p className="text-sm text-slate-400 dark:text-slate-500">Loading dashboard…</p>;
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">Dashboard</h1>
        <div className="flex items-center gap-2">
          {editing && (
            <button
              onClick={() => setAdding(true)}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700"
            >
              + Add widget
            </button>
          )}
          <button
            onClick={() => setEditing((e) => !e)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              editing
                ? "bg-emerald-600 text-white hover:bg-emerald-700"
                : "bg-slate-200 text-slate-800 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
            }`}
          >
            {editing ? "Done" : "Edit"}
          </button>
        </div>
      </div>

      <Grid
        className="layout"
        layout={gridLayout}
        cols={12}
        rowHeight={80}
        margin={[12, 12]}
        isDraggable={editing}
        isResizable={editing}
        draggableHandle=".widget-drag"
        onLayoutChange={applyPositions}
        onDragStop={savePositions}
        onResizeStop={savePositions}
        compactType="vertical"
      >
        {items.map((it) => {
          const def = WIDGETS[it.type];
          if (!def) return <div key={it.i} />;
          const Component = def.component;
          return (
            <div key={it.i}>
              <WidgetShell
                title={def.title}
                editing={editing}
                onRemove={() => removeWidget(it.i)}
                onConfig={def.configSchema ? () => setConfiguring(it.i) : undefined}
              >
                <Component config={it.config} />
              </WidgetShell>
            </div>
          );
        })}
      </Grid>

      {adding && <AddModal onClose={() => setAdding(false)} onAdd={addWidget} />}
      {configuring && (
        <ConfigModal
          item={items.find((it) => it.i === configuring)!}
          onClose={() => setConfiguring(null)}
          onSave={(cfg) => {
            setConfig(configuring, cfg);
            setConfiguring(null);
          }}
        />
      )}
    </div>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[80vh] w-full max-w-lg overflow-auto rounded-xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function AddModal({ onClose, onAdd }: { onClose: () => void; onAdd: (type: string) => void }) {
  return (
    <Modal title="Add a widget" onClose={onClose}>
      <div className="grid gap-2">
        {Object.values(WIDGETS).map((def) => (
          <button
            key={def.type}
            onClick={() => onAdd(def.type)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-left hover:border-blue-400 hover:bg-blue-50 dark:border-slate-700 dark:hover:border-blue-500 dark:hover:bg-slate-800"
          >
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{def.title}</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">{def.description}</p>
          </button>
        ))}
      </div>
    </Modal>
  );
}

function ConfigModal({
  item,
  onClose,
  onSave,
}: {
  item: WidgetItem;
  onClose: () => void;
  onSave: (config: Record<string, unknown>) => void;
}) {
  const def = WIDGETS[item.type];
  const [cfg, setCfg] = useState<Record<string, unknown>>({ ...item.config });

  return (
    <Modal title={`Configure · ${def.title}`} onClose={onClose}>
      <div className="space-y-3">
        {(def.configSchema ?? []).map((field) => (
          <label key={field.key} className="block">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">{field.label}</span>
            {field.type === "select" ? (
              <select
                value={String(cfg[field.key] ?? field.options?.[0]?.value ?? "")}
                onChange={(e) => setCfg({ ...cfg, [field.key]: e.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              >
                {field.options?.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            ) : (
              <input
                type="number"
                value={Number(cfg[field.key] ?? 0)}
                min={field.min}
                max={field.max}
                onChange={(e) => setCfg({ ...cfg, [field.key]: Number(e.target.value) })}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            )}
          </label>
        ))}
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="rounded-lg bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-200">
            Cancel
          </button>
          <button
            onClick={() => {
              // Numeric select values (e.g. months) come back as strings; coerce.
              const out: Record<string, unknown> = {};
              for (const [k, v] of Object.entries(cfg)) {
                out[k] = k === "months" ? Number(v) : v;
              }
              onSave(out);
            }}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700"
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
