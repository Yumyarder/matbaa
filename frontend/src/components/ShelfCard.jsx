import React from "react";
import { deleteProject, projectCoverUrl } from "../api";
import Icon from "./Icon.jsx";
import Tome from "./Tome.jsx";

// Haşiye's shelf: the Turkish alphabet (the start screen's rail, the
// library's A–Z) and a book's card, shared by the start screen and the
// library page.
export const ALPHABET = "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ".split("");

export function initial(title) {
  const t = (title || "").trim().replace(/^["“'‘(]+/, "");
  return t ? t[0].toLocaleUpperCase("tr") : "";
}

export const authorOf = (p) => (p.author && p.author !== "Unknown" ? p.author : "");

// Asks before deleting a book and its edits; resolves true when it was deleted.
export async function removeBook(p) {
  if (!window.confirm(`“${p.book_title}” ve üzerinde yaptığınız düzenlemeler silinsin mi? Bu geri alınamaz.`)) return false;
  await deleteProject(p.session_id).catch(() => {});
  return true;
}

export default function ShelfCard({ p, index = 0, onOpen, onRemoved }) {
  const author = authorOf(p);
  return (
    <li className="ed-card" style={{ "--i": index }}>
      <button type="button" className="ed-card__open" onClick={() => onOpen(p.session_id)}
              title={`${p.book_title}${p.updated ? ` — son düzenleme ${p.updated}` : ""}`}>
        <Tome title={p.book_title} author={author}
              cover={p.has_cover ? projectCoverUrl(p.session_id, p.updated) : null} />
        <span className="ed-card__text">
          <span className="ed-card__series">
            {[`${p.chapters} bölüm`, p.highlights ? `${p.highlights} vurgu` : null].filter(Boolean).join(" · ")}
          </span>
          <span className="ed-card__title">{p.book_title || "Adsız kitap"}</span>
          <span className="ed-card__rule" />
          {author && <span className="ed-card__author">{author}</span>}
          <span className="ed-card__foot">
            <span>Kitabı aç</span>
            <span className="ed-card__plus"><span className="ed-cross" aria-hidden="true" /></span>
          </span>
        </span>
      </button>
      <button type="button" className="ed-card__delete"
              onClick={async () => { if (await removeBook(p)) onRemoved?.(p); }}
              aria-label={`${p.book_title} kitabını sil`} title="Kitabı sil">
        <Icon name="close" />
      </button>
    </li>
  );
}
