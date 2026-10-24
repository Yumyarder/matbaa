// What a write will add to an existing note, read as text rather than as a
// programmer's diff: added lines marked, the reader's own lines around them
// shown faintly for place, gaps between places as a quiet ellipsis.
export default function NoteChanges({ diff }) {
  if (!diff) return <p className="note-changes__none">Değişiklik yok.</p>;
  const lines = diff.split("\n").filter((l) => !l.startsWith("---") && !l.startsWith("+++"));
  return (
    <div className="note-changes">
      {lines.map((l, i) => {
        if (l.startsWith("@@")) return <div key={i} className="note-changes__gap">⋯</div>;
        if (l.startsWith("+")) return <div key={i} className="note-changes__add">{l.slice(1) || " "}</div>;
        if (l.startsWith("-")) return <div key={i} className="note-changes__del">{l.slice(1) || " "}</div>;
        return <div key={i} className="note-changes__ctx">{l.slice(1) || " "}</div>;
      })}
    </div>
  );
}
