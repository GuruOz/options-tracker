import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getJSON, putJSON } from "../api/client";
import type { AdvisorConfig } from "../api/types";

export function SettingsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["advisor", "config"],
    queryFn: () => getJSON<AdvisorConfig>("/api/advisor/config"),
  });

  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data) {
      setProvider(data.provider ?? "anthropic");
      setModel(data.model ?? "");
      setBaseUrl(data.base_url ?? "");
    }
  }, [data]);

  const save = useMutation({
    mutationFn: () =>
      putJSON("/api/advisor/config", {
        provider,
        model: model || null,
        base_url: baseUrl || null,
        ...(apiKey ? { api_key: apiKey } : {}),
      }),
    onSuccess: () => {
      setApiKey("");
      setSaved(true);
      qc.invalidateQueries({ queryKey: ["advisor", "config"] });
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <div className="max-w-xl space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">Settings</h1>
        <p className="mt-1 text-sm text-slate-400 dark:text-slate-500">
          Configure the AI advisor. Bring your own key — it is stored encrypted
          and never shown again.
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">AI advisor</h2>
        <div className="space-y-4">
          <label className="block">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Provider</span>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            >
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="openai_compat">OpenAI-compatible</option>
            </select>
          </label>

          <label className="block">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
              Model {provider === "anthropic" && <span className="text-slate-400">(default: claude-opus-4-8)</span>}
            </span>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={provider === "anthropic" ? "claude-opus-4-8" : "gpt-4o"}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>

          {provider === "openai_compat" && (
            <label className="block">
              <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Base URL</span>
              <input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.openai.com/v1"
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            </label>
          )}

          <label className="block">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">API key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={data?.key_set ? "•••••••••• (saved — leave blank to keep)" : "Paste your API key"}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>

          <div className="flex items-center gap-3">
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending}
              className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {saved && <span className="text-xs font-semibold text-emerald-600">Saved</span>}
            {data?.key_set && <span className="text-xs text-slate-400">A key is currently stored.</span>}
          </div>
        </div>
      </div>

      <p className="text-xs text-slate-400 dark:text-slate-500">
        Suggestions are generated from an anonymized summary of your finances (no
        account numbers or names). They are educational information, not financial
        advice.
      </p>
    </div>
  );
}
