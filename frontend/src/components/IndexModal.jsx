import React, { useEffect, useState } from "react";
import { fetchIndex } from "../api";

// Dizin: the index Matbaa makes for a book that has none (app/auto_index.py) —
// the names the book uses and the concepts of the reader's vault, each with
// its printed pages. The reader can leave it out or take terms out of it.
export default function IndexModal({ session, onClose, onMetaChange }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => fetchIndex(session.session_id).then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [session.session_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const change = async (patch) => {
    setBusy(true);
    try {
      await onMetaChange(patch);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const removed = data?.removed || [];
  const entries = data?.entries || [];
  const names = entries.filter((e) => e.kind === "ad").length;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel modal-panel--wide" role="dialog" aria-label="Dizin" onClick={(e) => e.stopPropagation()}>
        <h2>Dizin</h2>
        {!data && !error && <p className="modal-panel__hint">Kitap taranıyor…</p>}
        {data?.turkish_only && (
          <p className="modal-panel__hint">Kendiliğinden dizin şimdilik Türkçe kitaplar için: adları Türkçe yazımın kesme işaretinden tanıyor.</p>
        )}
        {data?.printed && (
          <p className="modal-panel__hint">Bu kitabın kendi basılı dizini var; kitapta o, sayfalarına bağlı olarak duruyor.</p>
        )}
        {data?.available && (
          <>
            <p className="modal-panel__hint">
              Basılı dizini olmayan kitap için: kitapta geçen adlar ve kasandaki kavram notların (◦), her biri{" "}
              {data.paged ? "basılı sayfa numaralarıyla" : "geçtiği paragraflara bağlantılarla"}. {entries.length} madde
              ({names} ad, {entries.length - names} kavram).
            </p>
            <label className="workbench__notes-toggle">
              <input type="checkbox" checked={!!data.on} disabled={busy}
                     onChange={(e) => change({ auto_index: e.target.checked })} />
              Kitabın sonuna dizin ekle
            </label>
            <ul className="index-list">
              {entries.map((e) => (
                <li key={e.term}>
                  <span className="index-list__term">{e.term}{e.kind === "kavram" ? " ◦" : ""}</span>
                  <span className="index-list__pages">
                    {e.pages.length ? e.pages.slice(0, 10).join(", ") + (e.pages.length > 10 ? "…" : "") : `${e.places} yer`}
                  </span>
                  <button className="modal-link" disabled={busy} title="Bu maddeyi dizinden çıkar"
                          onClick={() => change({ index_removed: [...removed, e.term] })}>çıkar</button>
                </li>
              ))}
            </ul>
            {removed.length > 0 && (
              <p className="modal-panel__hint">
                Çıkarılanlar: {removed.map((t) => (
                  <button key={t} className="modal-link" disabled={busy} title="Geri al"
                          onClick={() => change({ index_removed: removed.filter((x) => x !== t) })}>{t} ↺</button>
                ))}
              </p>
            )}
          </>
        )}
        {error && <p className="modal-panel__error">{error}</p>}
        <div className="modal-actions">
          <button className="btn btn--primary" onClick={onClose}>Tamam</button>
        </div>
      </div>
    </div>
  );
}
