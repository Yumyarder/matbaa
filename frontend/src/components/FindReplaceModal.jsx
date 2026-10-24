import React, { useState } from "react";

export default function FindReplaceModal({ session, onClose, onApply }) {
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [useRegex, setUseRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(true);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);

  const buildRegex = () => {
    if (!find) return null;
    try {
      const pattern = useRegex ? find : find.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return new RegExp(pattern, "g" + (caseSensitive ? "" : "i"));
    } catch (err) {
      setError("Geçersiz regex: " + err.message);
      return null;
    }
  };

  const handlePreview = () => {
    setError(null);
    const re = buildRegex();
    if (!re) {
      setPreview(null);
      return;
    }
    let count = 0;
    let chapterCount = 0;
    session.chapters.forEach((ch) => {
      const matches = (ch.html.match(re) || []).length + ((ch.title || "").match(re) || []).length;
      if (matches > 0) {
        count += matches;
        chapterCount++;
      }
    });
    setPreview({ count, chapterCount });
  };

  const handleApply = () => {
    const re = buildRegex();
    if (!re) return;
    const changed = [];
    session.chapters.forEach((ch) => {
      const newHtml = ch.html.replace(re, replace);
      const newTitle = (ch.title || "").replace(re, replace);
      if (newHtml !== ch.html || newTitle !== ch.title) {
        changed.push({
          id: ch.id,
          html: newHtml,
          title: newTitle,
          eyebrow: ch.eyebrow,
          footnotes: ch.footnotes,
        });
      }
    });
    onApply(changed);
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h2>Toplu Bul ve Değiştir</h2>
        <p className="modal-panel__hint">
          Tüm bölümlerde arama yapar. PDF ayrıştırma sırasında sürekli tekrar eden bir hata varsa
          (ör. tüm "&" işaretleri "+" okunmuşsa) burada tek seferde düzeltebilirsiniz.
        </p>

        <label className="modal-field">
          Bul
          <input value={find} onChange={(e) => { setFind(e.target.value); setPreview(null); }} autoFocus />
        </label>
        <label className="modal-field">
          Değiştir
          <input value={replace} onChange={(e) => { setReplace(e.target.value); setPreview(null); }} />
        </label>

        <div className="modal-checkboxes">
          <label>
            <input
              type="checkbox"
              checked={useRegex}
              onChange={(e) => { setUseRegex(e.target.checked); setPreview(null); }}
            />
            Regex kullan
          </label>
          <label>
            <input
              type="checkbox"
              checked={caseSensitive}
              onChange={(e) => { setCaseSensitive(e.target.checked); setPreview(null); }}
            />
            Büyük/küçük harf duyarlı
          </label>
        </div>

        {error && <p className="modal-panel__error">{error}</p>}
        {preview && (
          <p className="modal-panel__preview">
            {preview.count} eşleşme, {preview.chapterCount} bölümde bulundu.
          </p>
        )}

        <div className="modal-actions">
          <button onClick={onClose}>İptal</button>
          <button onClick={handlePreview} disabled={!find}>Önizle</button>
          <button
            className="btn btn--primary"
            onClick={handleApply}
            disabled={!preview || preview.count === 0}
          >
            Tümüne Uygula
          </button>
        </div>
      </div>
    </div>
  );
}
