import React, { useEffect, useRef, useState } from "react";
import { STEPS, startEngine, takePendingPdf } from "./engine.js";

// While the engine loads in the browser: the steps it goes through, how much
// of the download has come, what it costs once, and where the books stay.
// Then the app, with a PDF the visitor dropped on the site's front page if
// there is one.
const PROBLEMS = {
  unsupported: "Bu tarayıcı Matbaa'yı çalıştıramıyor. Güncel bir Chrome, Edge, Firefox ya da Safari deneyin; "
    + "ya da Matbaa'yı Windows için indirin.",
  busy: "Matbaa bu tarayıcıda başka bir sekmede açık. O sekmeyle devam edin, ya da onu kapatıp bu sayfayı yenileyin.",
  failed: "Tezgâh kurulamadı. Sayfayı yenileyin; olmazsa bağlantınızı denetleyip yeniden deneyin.",
};
// no word from the engine for this long, and the reader is told why
const QUIET_MS = 30000;

const mb = (bytes) => (bytes / 1048576).toLocaleString("tr-TR", { maximumFractionDigits: 0 });

export default function BrowserBoot({ children }) {
  const [step, setStep] = useState(null);
  const [bytes, setBytes] = useState(null);
  const [quiet, setQuiet] = useState(false);
  const [ready, setReady] = useState(false);
  const [problem, setProblem] = useState(null);
  const [pending, setPending] = useState(null);
  const heard = useRef(Date.now());

  useEffect(() => {
    let live = true;
    const watch = setInterval(() => live && setQuiet(Date.now() - heard.current > QUIET_MS), 2000);
    startEngine((s, detail) => {
      if (!live) return;
      heard.current = Date.now();
      setQuiet(false);
      setStep(s);
      if (s === "download" && detail) setBytes(detail);
    })
      .then(() => takePendingPdf())
      .then((file) => {
        if (!live) return;
        setPending(file);
        setReady(true);
      })
      .catch((err) => {
        console.error(err);
        if (live) setProblem({ code: err.code || "failed", detail: err.message });
      })
      .finally(() => clearInterval(watch));
    return () => { live = false; clearInterval(watch); };
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
                {key === "download" && bytes && bytes.total > 0 && (
                  <span className="boot__bytes">
                    {mb(Math.min(bytes.done, bytes.total))} / {mb(bytes.total)} MB
                  </span>
                )}
              </li>
            ))}
          </ol>
          {bytes && bytes.total > 0 && at === 0 && (
            <div className="boot__bar" role="progressbar" aria-label="İndirme"
                 aria-valuemin={0} aria-valuemax={100}
                 aria-valuenow={Math.round((100 * Math.min(bytes.done, bytes.total)) / bytes.total)}>
              <span style={{ width: `${(100 * Math.min(bytes.done, bytes.total)) / bytes.total}%` }} />
            </div>
          )}
          {quiet && (
            <p className="boot__text boot__quiet" role="status">
              Bağlantı yavaş görünüyor. Bekleyebilirsiniz; inen dosyalar tarayıcıda kalır, sayfayı yenilerseniz
              kaldığı yerden hızlanır.
            </p>
          )}
          <p className="boot__text">
            Matbaa bu tarayıcıda çalışır. İlk açılışta yaklaşık 40 MB iner ve tarayıcıda saklanır; sonraki açılışlar
            hızlıdır. Kitaplarınız bu bilgisayardan çıkmaz.
          </p>
        </>
      )}
    </main>
  );
}
