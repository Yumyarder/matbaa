import React from "react";

// A book drawn as a cloth-bound edition (Haşiye): bookcloth in one of four
// colours chosen by the title, the PDF's cover tipped in as a plate, or —
// with no cover — the title stamped on a label. The same book always wears
// the same cloth.
const CLOTHS = ["bone", "iron", "chalk", "rubric"];

export function clothOf(title) {
  let h = 0;
  for (const ch of title || "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return CLOTHS[h % CLOTHS.length];
}

export default function Tome({ title, author, cover, size = "md" }) {
  const cloth = clothOf(title);
  return (
    <span className={`tome tome--${cloth} tome--${size}`} aria-hidden="true">
      {cover ? (
        <span className="tome__plate"><img src={cover} alt="" loading="lazy" /></span>
      ) : (
        <span className="tome__label">
          <span className="tome__label-title">{title || "Adsız kitap"}</span>
          {author && <span className="tome__label-author">{author}</span>}
        </span>
      )}
      <span className="tome__mark" />
    </span>
  );
}
