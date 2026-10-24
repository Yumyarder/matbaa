import React, { useEffect, useState } from "react";

// The chapter's warnings hung in the page's margin beside the paragraph each
// one is about (Haşiye). A warning quotes the start of its paragraph
// ('… bir cümle parçası olabilir: "özellikle 11 Eylül…"'); the quote finds
// the paragraph, a key sits at its line, and the note opens on a click with
// the paragraph marked. Warnings that quote nothing stay in the rail only.
const QUOTED = /["“]([^"”]{6,})["”][^"“”]*$/;

function fragment(message) {
  const m = (message || "").match(QUOTED);
  if (!m) return null;
  return m[1]
    .replace(/(\.\.\.|…)\s*$/, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 40)
    .toLocaleLowerCase("tr");
}

export default function MarginNotes({ bodyRef, notes, version }) {
  const [placed, setPlaced] = useState([]);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    setOpen(null);
    const body = bodyRef.current;
    if (!body || !notes?.length) {
      setPlaced([]);
      return undefined;
    }
    const place = () => {
      const blocks = [...body.children];
      const texts = blocks.map((b) => b.textContent.replace(/\s+/g, " ").toLocaleLowerCase("tr"));
      const out = [];
      notes.forEach((note, i) => {
        const f = fragment(note.message);
        const at = f ? texts.findIndex((t) => t.includes(f)) : -1;
        if (at >= 0) out.push({ ...note, key: i, top: blocks[at].offsetTop, height: blocks[at].offsetHeight });
      });
      setPlaced(out);
    };
    place();
    const watch = new ResizeObserver(place);
    watch.observe(body);
    return () => watch.disconnect();
  }, [bodyRef, notes, version]);

  if (!placed.length) return null;
  return (
    <div className="margin-notes">
      {placed.map((n) => (
        <div key={n.key} className="margin-note" style={{ top: n.top }}>
          {open === n.key && <span className="margin-note__span" style={{ height: n.height }} aria-hidden="true" />}
          <button
            type="button"
            className={`margin-note__key margin-note__key--${n.severity || "warning"}`}
            aria-expanded={open === n.key}
            aria-label={n.message}
            title={open === n.key ? "Notu kapat" : n.message}
            onClick={() => setOpen(open === n.key ? null : n.key)}
          />
          {open === n.key && (
            <p className="margin-note__text" role="note" style={{ top: n.height + 8 }}>{n.message}</p>
          )}
        </div>
      ))}
    </div>
  );
}
