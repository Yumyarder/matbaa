import React, { createContext, useContext, useEffect, useState } from "react";
import { fetchCounter, saveCounter } from "../api";
import { applyTheme, storedMode } from "../theme.js";
import AboutModal from "./AboutModal.jsx";

// The design languages the app can be set in, chosen at the top of every
// screen and remembered: "Haşiye", an annotated edition on bone paper in
// iron ink and rubric red (styles/hasiye.css, notes in DESIGN.md), the one
// Matbaa opens in, and "Gece Matbaası", the print shop at night it began as
// (charcoal, brass). Only the look changes; every screen works the same.
const MODES = [["hasiye", "Haşiye"], ["gece", "Gece Matbaası"]];

export const UiModeContext = createContext("hasiye");
export const useUi = () => useContext(UiModeContext);

export function useUiMode() {
  const [mode, setMode] = useState(storedMode);
  useEffect(() => applyTheme(mode), [mode]);
  return [mode, setMode];
}

// Told once, in the reader's app: the site's counter adds each exported
// book by its genre alone (app/counter.py); "Kapat" turns it off for good.
function CounterNotice() {
  const [state, setState] = useState(null);
  useEffect(() => { fetchCounter().then(setState).catch(() => setState(null)); }, []);
  if (!state || !state.active || !state.enabled || state.notice_seen) return null;
  const answer = (change) => saveCounter({ notice_seen: true, ...change }).then(setState).catch(() => setState(null));
  return (
    <p className="ui-strip__notice" role="status">
      Matbaa, dışa aktardığın kitapların yalnız türünü, adsız olarak sitedeki sayaca ekler.
      <button type="button" onClick={() => answer({})}>Tamam</button>
      <button type="button" onClick={() => answer({ enabled: false })}>Kapat</button>
    </p>
  );
}

export default function UiSwitch({ mode, onChange }) {
  const [about, setAbout] = useState(false);
  return (
    <div className="ui-strip">
      <button type="button" className="ui-strip__about" onClick={() => setAbout(true)}>Hakkında ve lisanslar</button>
      {about && <AboutModal onClose={() => setAbout(false)} />}
      <CounterNotice />
      <div className="ui-strip__switch" role="radiogroup" aria-label="Tasarım dili">
        {MODES.map(([id, label]) => (
          <button key={id} type="button" role="radio" aria-checked={mode === id}
                  className={`ui-strip__option ${mode === id ? "is-on" : ""}`} onClick={() => onChange(id)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
