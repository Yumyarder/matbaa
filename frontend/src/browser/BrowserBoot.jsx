import React, { useEffect, useState } from "react";
import { STEPS, startEngine, takePendingPdf } from "./engine.js";

// While the engine loads in the browser: the steps it goes through, what it
// costs once, and where the books stay. Then the app, with a PDF the visitor
// dropped on the site's front page if there is one.
const PROBLEMS = {
  unsupported: "Bu tarayıcı Matbaa'yı çalıştıramıyor. Güncel bir Chrome, Edge, Firefox ya da Safari deneyin; "
    + "ya da Matbaa'yı Windows için indirin.",
  busy: "Matbaa bu tarayıcıda başka bir sekmede açık. O sekmeyle devam edin, ya da onu kapatıp bu sayfayı yenileyin.",
  failed: "Tezgâh kurulamadı. Sayfayı yenileyin; olmazsa bağlantınızı denetleyip yeniden deneyin.",
};

export default function BrowserBoot({ children }) {
  const [step, setStep] = useState(null);
  const [ready, setReady] = useState(false);
  const [problem, setProblem] = useState(null);
  const [pending, setPending] = useState(null);

  useEffect(() => {
    let live = true;
    startEngine((s) => live && setStep(s))
      .then(() => takePendingPdf())
      .then((file) => {
        if (!live) return;
        setPending(file);
        setReady(true);
      })
      .catch((err) => {
        console.error(err);
        if (live) setProblem({ code: err.code || "failed", detail: err.message });
      });
    return () => { live = false; };
  }, []);

  if (ready) return children(pending);

  const at = STEPS.findIndex(([key]) => key === step);
  return (
    <main className="boot" aria-busy={!problem}>
      <p className="boot__mark">Matbaa <span className="boot__cross" aria-hidden="true" /> PDF'ten Kindle'a</p>
      {problem ? (
        <>
          <h1 className="boot__title">Tezgâh açılamadı.</h1>
          <p className="boot__text" role="alert">{PROBLEMS[problem.code] || PROBLEMS.failed}</p>
          {problem.code === "failed" && problem.detail && <p className="boot__detail">{problem.detail}</p>}
          <p className="boot__text"><a href="/">Matbaa'nın sayfasına dön</a></p>
        </>
      ) : (
        <>
          <h1 className="boot__title">Tezgâh kuruluyor.</h1>
          <ol className="boot__steps">
            {STEPS.map(([key, label], i) => (
              <li key={key} className={i < at ? "is-done" : i === at ? "is-now" : ""}
                  aria-current={i === at ? "step" : undefined}>
                {label}
              </li>
            ))}
          </ol>
          <p className="boot__text">
            Matbaa bu tarayıcıda çalışır. İlk açılışta yaklaşık 30 MB iner ve tarayıcıda saklanır; sonraki açılışlar
            hızlıdır. Kitaplarınız bu bilgisayardan çıkmaz.
          </p>
        </>
      )}
    </main>
  );
}
