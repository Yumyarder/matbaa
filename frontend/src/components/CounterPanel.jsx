import React, { useEffect, useState } from "react";
import { fetchCounterSummary } from "../api";

// The site's counter on the start screen (app/counter.py summary): how many
// books every reader's Matbaa has set, counting up as it arrives. Clicked,
// the genres open beneath it as a ledger, a tally mark a book and the fifth
// struck through in red (a bar once a genre outgrows a short row), with the
// latest books set under it. Nothing shows outside the reader's app or
// without the site.
const MAX_MARKS = 25;

function Tally({ n }) {
  const groups = Math.ceil(n / 5);
  const marks = [];
  for (let g = 0; g < groups; g++) {
    const k = Math.min(5, n - g * 5);
    const x0 = g * 22;
    for (let j = 0; j < Math.min(k, 4); j++) {
      marks.push(<line key={`${g}-${j}`} x1={x0 + 2 + j * 4} y1="2" x2={x0 + 2 + j * 4} y2="14" className="tally__mark" />);
    }
    if (k === 5) marks.push(<line key={`${g}-s`} x1={x0} y1="12" x2={x0 + 16} y2="4" className="tally__strike" />);
  }
  const width = Math.max(groups * 22, 4);
  return <svg className="tally__marks" width={width} height="16" viewBox={`0 0 ${width} 16`} aria-hidden="true">{marks}</svg>;
}

function when(hour) {
  const t = Date.parse(`${hour}:00:00Z`);
  if (Number.isNaN(t)) return "";
  const then = new Date(t);
  const now = new Date();
  const days = Math.round((new Date(now.toDateString()) - new Date(then.toDateString())) / 86400000);
  if (days === 0) {
    const h = then.getHours();
    return h < 5 ? "bu gece" : h < 12 ? "bu sabah" : h < 18 ? "bugün öğleden sonra" : "bu akşam";
  }
  return days === 1 ? "dün" : `${days} gün önce`;
}

export default function CounterPanel() {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState(0);

  useEffect(() => { fetchCounterSummary().then(setData).catch(() => setData(null)); }, []);
  useEffect(() => {
    if (!data?.available) return undefined;
    const target = data.total;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setShown(target);
      return undefined;
    }
    let frame;
    const start = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - start) / 1200);
      setShown(Math.round(target * (1 - (1 - p) ** 3)));
      if (p < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [data]);

  if (!data?.available) return null;
  const most = Math.max(1, ...data.genres.map((g) => g.n));
  const latest = data.recent.slice(0, 3);
  return (
    <section className="tally" aria-label="Dizilen kitaplar">
      <button type="button" className="tally__count" aria-expanded={open} aria-controls="tally-ledger"
              onClick={() => setOpen((o) => !o)}>
        <span className="tally__n">{shown.toLocaleString("tr-TR")}</span>
        <span className="tally__unit">kitap dizildi</span>
        <span className={`ed-cross tally__toggle ${open ? "is-open" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div id="tally-ledger" className="tally__ledger">
          <ol className="tally__rows">
            {data.genres.map((g) => (
              <li key={g.id} className="tally__row">
                <span className="tally__genre">{g.label}</span>
                {most <= MAX_MARKS
                  ? <Tally n={g.n} />
                  : <span className="tally__bar"><span style={{ width: `${(100 * g.n) / most}%` }} /></span>}
                <span className="tally__k">{g.n.toLocaleString("tr-TR")}</span>
              </li>
            ))}
          </ol>
          {latest.length > 0 && (
            <p className="tally__latest">
              Son dizilenler: {latest.map((r, i) => (
                <span key={i}>{i > 0 ? "; " : ""}{r.label}, {when(r.hour)}</span>
              ))}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
