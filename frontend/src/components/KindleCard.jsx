import React, { useEffect, useRef, useState } from "react";
import { dictionaryRefresh, dictionaryRefreshStatus, installKindleDictionary, installKindleFonts, kindleDevice } from "../api";

// Kindle'ım: what the plugged-in Kindle has of what Matbaa gives it — its
// typefaces in the Aa menu, the Turkish dictionary for Turkish books — and
// one button for whatever is missing. Only files are added to the Kindle;
// the dictionary is made again, and put in place of the old one, when books
// were added since it was made (their word forms are what the Kindle finds).
export default function KindleCard({ ready }) {
  const [dev, setDev] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [job, setJob] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    if (!ready) { setDev(null); return; }
    kindleDevice().then(setDev).catch(() => setDev(null));
  }, [ready]);
  useEffect(() => () => clearInterval(timer.current), []);

  if (!ready || !dev?.ready) return null;
  const fontsMissing = dev.fonts.filter((f) => !f.installed);
  const dict = dev.matbaa_dictionary || {};
  const needsDict = dict.built && (!dict.on_kindle || dict.outdated);

  const prepare = async () => {
    setBusy(true);
    setError(null);
    try {
      let d = dev;
      if (fontsMissing.length) d = await installKindleFonts();
      if (needsDict) d = await installKindleDictionary();
      setDev(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    setError(null);
    try {
      setJob(await dictionaryRefresh());
      clearInterval(timer.current);
      timer.current = setInterval(async () => {
        const st = await dictionaryRefreshStatus().catch(() => null);
        if (!st) return;
        setJob(st);
        if (st.state !== "running") {
          clearInterval(timer.current);
          if (st.state === "done") kindleDevice().then(setDev).catch(() => {});
        }
      }, 3000);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="kindle-card" role="status">
      <span className="notebook__label">Kindle'ım</span>
      <span>
        {dev.fonts.map((f) => (
          <span key={f.family} className={`kindle-card__item ${f.installed ? "is-on" : ""}`}>
            {f.label} {f.installed ? "✓" : "yok"}
          </span>
        ))}
        <span className={`kindle-card__item ${dict.on_kindle ? "is-on" : ""}`}>
          Türkçe sözlük {dict.on_kindle ? (dict.outdated ? "✓ (yenisi var)" : "✓") : "yok"}
        </span>
      </span>
      {(fontsMissing.length > 0 || needsDict) && (
        <button className="btn" disabled={busy} onClick={prepare}>
          {busy ? "Kindle'a kopyalanıyor…" : "Kindle'ı hazırla"}
        </button>
      )}
      {dict.on_kindle && dict.new_books > 0 && job?.state !== "running" && job?.state !== "done" && (
        <button className="btn" onClick={refresh}
                title="Sözlük, yeni kitapların kelime biçimleriyle yeniden yapılır ve Kindle'dakinin yerine konur (birkaç dakika)">
          Sözlüğü yenile ({dict.new_books} yeni kitap)
        </button>
      )}
      {job?.state === "running" && <span className="notebook__hint">Sözlük yenileniyor: {job.step}…</span>}
      {job?.state === "done" && (
        <span className="kindle-card__item is-on">
          Sözlük yenilendi{job.result?.kindle ? " ve Kindle'a kondu" : ""}
        </span>
      )}
      {job?.state === "error" && <span className="modal-panel__error">Sözlük yenilenemedi: {job.message}</span>}
      {dict.on_kindle && (
        <span className="notebook__hint">
          Kindle'da bir kez: Ayarlar → Dil ve Sözlükler → Sözlükler → Türkçe → “Matbaa Türkçe Sözlük”.
          Yazı tipleri Aa menüsünde.
        </span>
      )}
      {error && <span className="modal-panel__error">{error}</span>}
    </div>
  );
}
