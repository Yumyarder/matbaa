import React, { useCallback, useRef, useState } from "react";
import CounterPanel from "./CounterPanel.jsx";
import RecentProjects from "./RecentProjects";
import HasiyeStart from "./HasiyeStart.jsx";
import { useUi } from "./UiSwitch.jsx";

export default function UploadModule({ onFileSelected, isConverting, progress, error, onOpenProject, onOpenNotebook,
                                       onOpenLibrary }) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef(null);
  const hasiye = useUi() === "hasiye";

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) onFileSelected(file);
    },
    [onFileSelected]
  );

  // Haşiye sets the start screen as an edition's front matter (HasiyeStart)
  if (hasiye) {
    return (
      <HasiyeStart onFileSelected={onFileSelected} isConverting={isConverting} progress={progress}
                   error={error} onOpenProject={onOpenProject} onOpenNotebook={onOpenNotebook}
                   onOpenLibrary={onOpenLibrary} />
    );
  }

  return (
    <div className="upload-screen">
      <div className="upload-screen__brand">
        <span className="ruler-mark">01</span>
        <h1>Matbaa</h1>
        <p className="upload-screen__tagline">
          Akademik PDF'ini Kindle için mükemmel biçimlendirilmiş bir EPUB'a
          dönüştür — canlı bir dizgi tezgâhıyla.
        </p>
      </div>

      <div
        className={`dropzone ${isDragging ? "dropzone--active" : ""} ${isConverting ? "dropzone--busy" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => !isConverting && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !isConverting) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        role="button"
        tabIndex={0}
        aria-label="PDF seçin ya da buraya bırakın"
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(e) => e.target.files?.[0] && onFileSelected(e.target.files[0])}
        />
        {!isConverting ? (
          <>
            <div className="dropzone__icon" aria-hidden="true">
              <svg viewBox="0 0 48 48" width="40" height="40">
                <path
                  d="M24 6v24m0 0-9-9m9 9 9-9M9 34v4a4 4 0 0 0 4 4h22a4 4 0 0 0 4-4v-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <p className="dropzone__title">Akademik bir PDF'i buraya bırakın</p>
            <p className="dropzone__hint">ya da göz atmak için tıklayın — ~200MB'a kadar</p>
          </>
        ) : (
          <div className="dropzone__progress">
            <p className="dropzone__title">Sayfalar taranıyor…</p>
            <div className="progress-bar">
              <div className="progress-bar__fill" style={{ width: `${progress}%` }} />
            </div>
            <p className="dropzone__hint">
              {progress < 100 ? `Yükleniyor — %${progress}` : "Sayfa küçük resimleri hazırlanıyor…"}
            </p>
          </div>
        )}
      </div>

      {error && <p className="upload-screen__error">{error}</p>}

      {!isConverting && onOpenNotebook && (
        <button type="button" className="notebook-entry" onClick={onOpenNotebook}>
          <span className="notebook-entry__title">Okuma Defteri</span>
          <span className="notebook-entry__text">Kindle'da altını çizdiklerin ve notların, Obsidian'a</span>
        </button>
      )}

      {!isConverting && <div className="upload-screen__tally"><CounterPanel /></div>}
      {!isConverting && onOpenProject && <RecentProjects onOpen={onOpenProject} />}

      <ul className="upload-screen__rules">
        <li>Reklam/gereksiz sayfaları dönüştürmeden önce çıkarabilirsiniz</li>
        <li>Üst-alt bilgi bantları otomatik kırpılır</li>
        <li>Dipnotlar ve bölüm sonu notları metnin ortasına değil, bölüm sonuna eklenir</li>
        <li>Soluk, italik ve büyük punto başlıklar otomatik tanınır — hepsi editlenebilir</li>
      </ul>
    </div>
  );
}
