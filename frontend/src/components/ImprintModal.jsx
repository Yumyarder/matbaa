import React, { useState } from "react";
import { lookupImprint } from "../api";

// Künye: what the book's own imprint page says of the edition (app/imprint.py),
// correctable here; completed online by the ISBN only when asked, and only
// where the book left a field empty. It goes into the EPUB's metadata, and on
// request into a page "Bu baskı hakkında" at the end of the book.
const FIELDS = [
  ["isbn", "ISBN"],
  ["translator", "Çeviren"],
  ["editor", "Editör / yayına hazırlayan"],
  ["original_title", "Özgün adı"],
  ["publisher", "Yayınevi"],
  ["edition", "Baskı (kaçıncı)"],
  ["year", "Yıl"],
];

export default function ImprintModal({ session, onClose, onMetaChange, onSessionReplace }) {
  const [draft, setDraft] = useState(() =>
    Object.fromEntries(FIELDS.map(([k]) => [k, session.imprint?.[k] ?? ""])));
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const changed = FIELDS.some(([k]) => String(draft[k] ?? "") !== String(session.imprint?.[k] ?? ""));

  const save = async () => {
    setError(null);
    try {
      await onMetaChange({ imprint: { ...draft } });
      setNote("Kaydedildi.");
    } catch (e) {
      setError(e.message);
    }
  };

  const lookUp = async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      if (changed) await onMetaChange({ imprint: { ...draft } });
      const r = await lookupImprint(session.session_id);
      onSessionReplace(r.session);
      setDraft(Object.fromEntries(FIELDS.map(([k]) => [k, r.session.imprint?.[k] ?? ""])));
      if (!r.found) setNote("Bu ISBN ile bir kayıt bulunamadı.");
      else {
        const parts = [];
        if (r.filled.length) parts.push(`${r.filled.map((k) => FIELDS.find(([f]) => f === k)?.[1]).join(", ")} eklendi`);
        else parts.push("künyede eksik alan yoktu");
        if (r.found.cover) parts.push("bir kapak bulundu (kapak menüsünde “İnternet kapağı”)");
        setNote(`${r.found.source}: ${parts.join("; ")}.`);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" role="dialog" aria-label="Künye" onClick={(e) => e.stopPropagation()}>
        <h2>Künye</h2>
        <p className="modal-panel__hint">
          Kitabın künye sayfasından okundu; düzeltebilirsin. EPUB'ın bilgilerine yazılır (Kindle'da kitap
          bilgisinde görünür).
        </p>
        <div className="imprint-grid">
          {FIELDS.map(([key, label]) => (
            <label key={key} className="modal-field">
              {label}
              <input value={draft[key] ?? ""} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
            </label>
          ))}
        </div>
        <label className="workbench__notes-toggle">
          <input type="checkbox" checked={!!session.imprint_page}
                 onChange={(e) => onMetaChange({ imprint_page: e.target.checked })} />
          Kitabın sonuna “Bu baskı hakkında” sayfası ekle
        </label>
        {note && <p className="modal-panel__hint">{note}</p>}
        {error && <p className="modal-panel__error">{error}</p>}
        <div className="modal-actions">
          <button className="btn" disabled={busy || !draft.isbn} onClick={lookUp}
                  title="Yalnız ISBN gönderilir; yalnız boş alanlar doldurulur">
            {busy ? "Bakılıyor…" : "İnternetten tamamla"}
          </button>
          <button className="btn" onClick={onClose}>Kapat</button>
          <button className="btn btn--primary" disabled={!changed} onClick={save}>Kaydet</button>
        </div>
      </div>
    </div>
  );
}
