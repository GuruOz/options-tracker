import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteJSON, getJSON, postForm } from "../api/client";
import type {
  StatementLogEntry,
  StatementSource,
  StatementUploadResult,
  StatementsResponse,
} from "../api/types";
import { useScope } from "../hooks/useScope";

const SOURCES: { key: StatementSource; label: string; hint: string }[] = [
  { key: "cpf", label: "CPF", hint: "CPF “Transaction history” PDF" },
  { key: "endowus", label: "Endowus", hint: "Endowus “Statement of Account” PDF" },
];

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

function UploadCard({ owner }: { owner: { owner: string; label: string } }) {
  const qc = useQueryClient();
  const [source, setSource] = useState<StatementSource>("cpf");
  const [result, setResult] = useState<StatementUploadResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return postForm<StatementUploadResult>(
        `/api/statements/upload?source=${source}&owner=${encodeURIComponent(owner.owner)}`,
        form,
      );
    },
    onSuccess: (r) => {
      setResult(r);
      if (inputRef.current) inputRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["statements"] });
      qc.invalidateQueries({ queryKey: ["owners"] });
      qc.invalidateQueries({ queryKey: ["networth"] });
    },
    onError: () => setResult({ status: "error", message: "Upload failed." }),
  });

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
        {owner.label}
      </h2>
      <div className="mt-2 flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
        {SOURCES.map((s) => (
          <button
            key={s.key}
            onClick={() => {
              setSource(s.key);
              setResult(null);
            }}
            className={`rounded-md px-3 py-1 text-xs font-semibold transition-colors ${
              source === s.key
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-600 dark:text-slate-50"
                : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
        {SOURCES.find((s) => s.key === source)?.hint}
      </p>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        disabled={upload.isPending}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload.mutate(f);
        }}
        className="mt-3 block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-200 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-slate-800 hover:file:bg-slate-300 dark:text-slate-300 dark:file:bg-slate-700 dark:file:text-slate-100"
      />
      {upload.isPending && (
        <p className="mt-2 text-xs text-slate-400">Parsing…</p>
      )}
      {result && (
        <div
          className={`mt-3 rounded-lg px-3 py-2 text-xs ${
            result.status === "ok"
              ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
              : result.status === "duplicate"
                ? "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200"
                : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-200"
          }`}
        >
          {result.status === "ok" ? (
            <>
              Imported {result.balances ?? 0} balances, {result.transactions ?? 0}{" "}
              transactions, {result.holdings ?? 0} holdings
              {result.period?.[1] ? ` · through ${fmtDate(result.period[1])}` : ""}.
              {result.warnings && result.warnings.length > 0 && (
                <div className="mt-1 text-amber-700 dark:text-amber-300">
                  {result.warnings.length} warning(s).
                </div>
              )}
            </>
          ) : (
            result.message ?? result.status
          )}
        </div>
      )}
    </div>
  );
}

function HistoryTable() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["statements"],
    queryFn: () => getJSON<StatementsResponse>("/api/statements"),
  });
  const del = useMutation({
    mutationFn: (id: number) => deleteJSON(`/api/statements/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["statements"] });
      qc.invalidateQueries({ queryKey: ["networth"] });
    },
  });

  const rows = data?.statements ?? [];
  if (rows.length === 0) {
    return (
      <p className="text-sm text-slate-400 dark:text-slate-500">
        No statements uploaded yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-400 dark:bg-slate-800 dark:text-slate-500">
          <tr>
            <th className="px-4 py-2">Account</th>
            <th className="px-4 py-2">Source</th>
            <th className="px-4 py-2">Period</th>
            <th className="px-4 py-2">Rows</th>
            <th className="px-4 py-2">Uploaded</th>
            <th className="px-4 py-2"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {rows.map((s: StatementLogEntry) => (
            <tr key={s.id} className="text-slate-700 dark:text-slate-200">
              <td className="px-4 py-2 font-medium">{s.account_id}</td>
              <td className="px-4 py-2 uppercase">{s.source}</td>
              <td className="px-4 py-2">
                {fmtDate(s.period_start)} – {fmtDate(s.period_end)}
              </td>
              <td className="px-4 py-2 text-slate-500 dark:text-slate-400">
                {s.summary
                  ? `${s.summary.balances}b / ${s.summary.transactions}t / ${s.summary.holdings}h`
                  : "—"}
              </td>
              <td className="px-4 py-2 text-slate-500 dark:text-slate-400">
                {fmtDate(s.uploaded_at)}
              </td>
              <td className="px-4 py-2 text-right">
                <button
                  onClick={() => del.mutate(s.id)}
                  className="rounded-md bg-red-50 px-2 py-1 text-xs font-semibold text-red-600 hover:bg-red-100 dark:bg-red-950 dark:text-red-300"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function UploadsPage() {
  const { owners } = useScope();
  const people = owners.length ? owners : [{ owner: "me", label: "Me" }];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
          Statement uploads
        </h1>
        <p className="mt-1 text-sm text-slate-400 dark:text-slate-500">
          CPF and Endowus have no API — upload the monthly PDF statements. Each
          upload is stored as a dated snapshot; re-uploading the same file is a
          no-op.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {people.map((o) => (
          <UploadCard key={o.owner} owner={o} />
        ))}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
          Upload history
        </h2>
        <HistoryTable />
      </div>
    </div>
  );
}
