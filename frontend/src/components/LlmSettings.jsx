import React, { useEffect, useState } from "react";
import { fetchLlmSettings, saveLlmSettings } from "../api";

// The reader's own language model, optional: a provider and a key they type
// themselves (kept in ~/.matbaa/llm.json, never shown again), or a model on
// this computer (Ollama) found by itself. Without one, "Kitaba sor" copies
// its request for ChatGPT instead.
const KINDS = [
  ["anthropic", "Anthropic (Claude)", "", "claude-sonnet-5-5"],
  ["openai", "OpenAI", "", "gpt-5"],
  ["local", "Bu bilgisayardaki model (Ollama)", "http://127.0.0.1:11434/v1", ""],
  ["compatible", "OpenAI uyumlu başka bir sunucu", "", ""],
];

export default function LlmSettings({ onClose, onSaved }) {
  const [view, setView] = useState(null);
  const [kind, setKind] = useState("anthropic");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchLlmSettings().then((v) => {
      setView(v);
      const local = (v.base_url || "").includes("11434");
      setKind(v.provider === "anthropic" ? "anthropic" : local ? "local" : v.base_url ? "compatible"
        : v.provider === "openai" ? "openai" : v.local ? "local" : "anthropic");
      setModel(v.model || (v.local && v.local[0]) || "");
      setBaseUrl(v.base_url || "");
    }).catch((e) => setError(e.message));
  }, []);

  const choose = (k) => {
    setKind(k);
    const [, , url, suggested] = KINDS.find(([id]) => id === k);
    setBaseUrl(url);
    if (k === "local" && view?.local?.length) setModel(view.local[0]);
    else if (suggested) setModel(suggested);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const provider = kind === "anthropic" ? "anthropic" : "openai";
      const status = await saveLlmSettings({ provider, model, api_key: key, base_url: baseUrl });
      onSaved?.(status);
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const forget = async () => {
    setBusy(true);
    try {
      onSaved?.(await saveLlmSettings({ clear: true }));
      onClose();
    } finally {
      setBusy(false);
    }
  };
  const needsKey = kind === "anthropic" || kind === "openai";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" role="dialog" aria-label="Dil modeli" onClick={(e) => e.stopPropagation()}>
        <h2>Dil modeli</h2>
        <p className="modal-panel__hint">
          İsteğe bağlı. Ayarlanınca “Kitaba sor” yanıtı kendisi alır; yoksa isteği ChatGPT'ye kopyalarsın. Anahtar
          bu bilgisayarda kalır ve bir daha gösterilmez.
        </p>
        {view?.local && (
          <p className="modal-panel__hint">Bu bilgisayarda bir yerel model sunucusu çalışıyor: {view.local.join(", ")}.</p>
        )}
        <label className="modal-field">
          Nereden
          <select className="workbench__lang-select" value={kind} onChange={(e) => choose(e.target.value)}>
            {KINDS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
        <label className="modal-field">
          Model
          <input value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
        {needsKey && (
          <label className="modal-field">
            API anahtarı {view?.has_key ? "(kayıtlı; değiştirmek için yenisini yaz)" : ""}
            <input type="password" value={key} autoComplete="off" onChange={(e) => setKey(e.target.value)} />
          </label>
        )}
        {!needsKey && (
          <label className="modal-field">
            Sunucu adresi
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://127.0.0.1:11434/v1" />
          </label>
        )}
        {error && <p className="modal-panel__error">{error}</p>}
        <div className="modal-actions">
          {view?.available && <button className="btn" disabled={busy} onClick={forget}>Ayarı sil</button>}
          <button className="btn" onClick={onClose}>Vazgeç</button>
          <button className="btn btn--primary" disabled={busy || !model.trim() || (needsKey && !key && !view?.has_key)}
                  onClick={save}>Kaydet</button>
        </div>
      </div>
    </div>
  );
}
