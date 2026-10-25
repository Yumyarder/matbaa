import React from "react";
import { IN_BROWSER, STEPS, useEngine } from "./engine.js";

// One quiet line while the engine loads behind the app (browser build only):
// which step it is at and, while it downloads, how many megabytes have come.
// Nothing once it is ready. `queued` is for a PDF already chosen: it waits
// for the engine and the reader is told so.
const mb = (bytes) => (bytes / 1048576).toLocaleString("tr-TR", { maximumFractionDigits: 0 });

export function engineShare(engine) {
  const b = engine.bytes;
  if (engine.step !== "download" || !b || !b.total) return engine.step ? 100 : 0;
  return Math.round((100 * Math.min(b.done, b.total)) / b.total);
}

export function engineText(engine, queued = false) {
  const b = engine.bytes;
  const step = (STEPS.find(([key]) => key === engine.step) || STEPS[0])[1];
  const amount = engine.step === "download" && b && b.total
    ? `: ${mb(Math.min(b.done, b.total))} / ${mb(b.total)} MB`
    : "…";
  return queued ? `Kitabınız sırada. ${step}${amount}` : `${step}${amount}`;
}

export default function EngineStatus({ className = "" }) {
  const engine = useEngine();
  if (!IN_BROWSER || engine.ready || engine.problem) return null;
  return (
    <p className={`engine-line ${className}`} role="status">
      <span className="engine-line__text">{engineText(engine)}</span>
      {engine.step === "download" && (
        <span className="engine-line__note"> Yalnız ilk açılışta iner, sonra bu tarayıcıda kalır.</span>
      )}
      <span className="engine-line__bar" aria-hidden="true"><span style={{ width: `${engineShare(engine)}%` }} /></span>
    </p>
  );
}
