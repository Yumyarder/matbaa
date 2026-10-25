import React from "react";

// In the browser build, where the start screen leads to Okuma Defteri,
// Kelime Defteri or Kindle'ım: they need the Kindle on a cable and the
// reader's Obsidian vault on disk, which a web page cannot reach.
export default function DesktopOnly({ onBack }) {
  return (
    <main className="boot">
      <p className="boot__mark">Matbaa <span className="boot__cross" aria-hidden="true" /> PDF'ten Kindle'a</p>
      <h1 className="boot__title">Bu bölüm Windows sürümünde.</h1>
      <p className="boot__text">
        Okuma Defteri, Kelime Defteri ve Kindle'ım, Kindle'ı bilgisayara kabloyla bağlamayı ve Obsidian kasanıza
        yazmayı gerektirir. Bir web sayfası bunlara erişemez; Windows için Matbaa erişir.
      </p>
      <p className="boot__text">
        Kitap dizmek, kitaplık ve EPUB burada da çalışır.
      </p>
      <p className="boot__actions">
        <button type="button" className="boot__button" onClick={onBack}>Tezgâha dön</button>
        <a className="boot__link" href="/#indir">Windows için indir</a>
      </p>
    </main>
  );
}
