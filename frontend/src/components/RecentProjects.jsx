import React, { useEffect, useState } from "react";
import { deleteProject, fetchProjects, projectCoverUrl } from "../api";

// Kitaplığım: the books converted before, kept on disk
// (backend/app/session_store.py), as a shelf of covers — each with what the
// reader marked in it on the Kindle (highlights, words looked up). A closed
// app or a restarted computer no longer costs the work done on them.
function Spine({ p }) {
  // a book without a cover is set as its spine: title and author in type
  return (
    <span className="shelf__spine">
      <span className="shelf__spine-title">{p.book_title || "Adsız kitap"}</span>
      {p.author && p.author !== "Unknown" && <span className="shelf__spine-author">{p.author}</span>}
    </span>
  );
}

export default function RecentProjects({ onOpen }) {
  const [projects, setProjects] = useState(null);

  const load = () => fetchProjects().then(setProjects).catch(() => setProjects([]));
  useEffect(() => { load(); }, []);

  if (!projects || projects.length === 0) return null;

  const remove = async (p) => {
    if (!window.confirm(`“${p.book_title}” ve üzerinde yaptığınız düzenlemeler silinsin mi? Bu geri alınamaz.`)) return;
    await deleteProject(p.session_id).catch(() => {});
    load();
  };

  return (
    <section className="shelf" aria-label="Kitaplığım">
      <h2 className="shelf__title">Kitaplığım <span>{projects.length} kitap</span></h2>
      <ul className="shelf__grid">
        {projects.map((p) => (
          <li key={p.session_id} className="shelf__book">
            <button type="button" className="shelf__open" onClick={() => onOpen(p.session_id)}
                    title={`${p.book_title}${p.updated ? ` — son düzenleme ${p.updated}` : ""}`}>
              {p.has_cover
                ? <img className="shelf__cover" src={projectCoverUrl(p.session_id, p.updated)} alt="" loading="lazy" />
                : <Spine p={p} />}
              <span className="shelf__name">{p.book_title || "Adsız kitap"}</span>
              <span className="shelf__meta">
                {[p.author && p.author !== "Unknown" ? p.author : null].filter(Boolean).join("")}
              </span>
              <span className="shelf__marks">
                {[`${p.chapters} bölüm`, p.highlights ? `${p.highlights} vurgu` : null,
                  p.words ? `${p.words} kelime` : null].filter(Boolean).join(" · ")}
              </span>
            </button>
            <button type="button" className="shelf__delete" onClick={() => remove(p)}
                    aria-label={`${p.book_title} kitabını sil`} title="Kitabı sil">×</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
