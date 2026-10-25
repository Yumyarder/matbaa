import React, { useEffect, useState } from "react";
import { takePendingPdf, useEngine } from "./engine.js";

// The app at once, with a PDF the visitor dropped on the site's front page if
// there is one; the engine loads behind it (engine.js). Only when the engine
// cannot run here at all does this page take the app's place, and say why.
const PROBLEMS = {
  unsupported: "Bu tarayıcı Matbaa'yı çalıştıramıyor. Güncel bir Chrome, Edge, Firefox ya da Safari deneyin; "
    + "ya da Matbaa'yı Windows için indirin.",
  busy: "Matbaa bu tarayıcıda başka bir sekmede açık. O sekmeyle devam edin, ya da onu kapatıp bu sayfayı yenileyin.",
  failed: "Tezgâh kurulamadı. Sayfayı yenileyin; olmazsa bağlantınızı denetleyip yeniden deneyin.",
};

export default function BrowserBoot({ children }) {
  const engine = useEngine();
  const [pending, setPending] = useState(null);

  useEffect(() => {
    let live = true;
    takePendingPdf().then((file) => live && setPending(file));
    return () => { live = false; };
  }, []);

  if (!engine.problem) return children(pending);

  return (
    <main className="boot">
      <p className="boot__mark">Matbaa <span className="boot__cross" aria-hidden="true" /> PDF'ten Kindle'a</p>
      <h1 className="boot__title">Tezgâh açılamadı.</h1>
      <p className="boot__text" role="alert">{PROBLEMS[engine.problem] || PROBLEMS.failed}</p>
      {engine.problem === "failed" && engine.detail && <p className="boot__detail">{engine.detail}</p>}
      <p className="boot__text"><a href="/">Matbaa'nın sayfasına dön</a></p>
    </main>
  );
}
