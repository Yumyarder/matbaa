import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchGenres, fetchProjects } from "../api";
import Icon from "./Icon.jsx";
import ShelfCard, { ALPHABET, authorOf, initial } from "./ShelfCard.jsx";

// Kitaplık (Haşiye): every book converted on this computer, as the cloth-
// bound editions of the start screen's shelf, in six orders: all by title,
// the ones read (highlights from the Kindle), the latest by month, by
// author, by genre (app/genre.py), and A–Z with the Turkish alphabet as an
// index.
const TABS = [
  ["all", "Tümü"],
  ["read", "Okunanlar"],
  ["recent", "Son eklenenler"],
  ["author", "Yazara göre"],
  ["genre", "Türe göre"],
  ["alpha", "A–Z"],
];

const byTitle = (a, b) => (a.book_title || "").localeCompare(b.book_title || "", "tr");
const monthOf = (p) => {
  const d = p.updated ? new Date(p.updated.replace(" ", "T")) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleDateString("tr-TR", { month: "long", year: "numeric" })
    : "Tarihsiz";
};

function groupsFor(tab, books, genres = []) {
  if (tab === "read") {
    const read = books.filter((p) => p.highlights > 0).sort((a, b) => b.highlights - a.highlights);
    return [{ key: "read", title: null, books: read }];
  }
  if (tab === "recent") {
    const out = [];
    for (const p of [...books].sort((a, b) => (b.mtime || 0) - (a.mtime || 0))) {
      const m = monthOf(p);
      if (!out.length || out[out.length - 1].title !== m) out.push({ key: m, title: m, books: [] });
      out[out.length - 1].books.push(p);
    }
    return out;
  }
  if (tab === "author") {
    const map = new Map();
    for (const p of books) {
      const a = authorOf(p) || "Yazarı bilinmeyen";
      if (!map.has(a)) map.set(a, []);
      map.get(a).push(p);
    }
    return [...map.entries()]
      .sort(([a], [b]) => (a === "Yazarı bilinmeyen") - (b === "Yazarı bilinmeyen") || a.localeCompare(b, "tr"))
      .map(([a, list]) => ({ key: a, title: a, books: list.sort(byTitle) }));
  }
  if (tab === "genre") {
    // in the order genres are listed, the ones with no books left out
    const map = new Map(genres.map((g) => [g.id, []]));
    for (const p of books) {
      const id = map.has(p.genre) ? p.genre : "diger";
      if (!map.has(id)) map.set(id, []);
      map.get(id).push(p);
    }
    const label = (id) => genres.find((g) => g.id === id)?.label || "Diğer";
    return [...map.entries()].filter(([, list]) => list.length)
      .map(([id, list]) => ({ key: id, title: label(id), books: list.sort(byTitle) }));
  }
  if (tab === "alpha") {
    const map = new Map();
    for (const p of [...books].sort(byTitle)) {
      const l = initial(p.book_title) || "#";
      if (!map.has(l)) map.set(l, []);
      map.get(l).push(p);
    }
    return [...map.entries()].map(([l, list]) => ({ key: l, title: l, books: list, letter: l }));
  }
  return [{ key: "all", title: null, books: [...books].sort(byTitle) }];
}

export default function LibraryPage({ onBack, onOpenProject }) {
  const [projects, setProjects] = useState(null);
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [genres, setGenres] = useState([]);
  const groupRefs = useRef({});
  useEffect(() => { fetchGenres().then(setGenres).catch(() => setGenres([])); }, []);

  const load = () => fetchProjects().then(setProjects).catch(() => setProjects([]));
  useEffect(() => { load(); }, []);

  const q = query.trim().toLocaleLowerCase("tr");
  const matched = useMemo(() => (projects || []).filter((p) => !q
    || (p.book_title || "").toLocaleLowerCase("tr").includes(q)
    || authorOf(p).toLocaleLowerCase("tr").includes(q)), [projects, q]);
  const groups = groupsFor(tab, matched, genres);
  const shown = groups.reduce((n, g) => n + g.books.length, 0);
  const letters = new Set(tab === "alpha" ? groups.map((g) => g.letter) : []);
  let index = 0;

  return (
    <div className="lib">
      <header className="lib__head">
        <button type="button" className="ed__link lib__back" onClick={onBack}>
          <Icon name="back" /> Matbaa
        </button>
        <div className="lib__titles">
          <h1 className="lib__title">Kitaplık</h1>
          <p className="lib__count">
            {projects === null ? "Yükleniyor…" : q ? `${shown} / ${projects.length} kitap` : `${projects.length} kitap`}
          </p>
        </div>
        <label className="lib__search">
          <span className="ed__label">Ara</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="kitap adı ya da yazar" aria-label="Kitaplıkta ara" />
        </label>
      </header>

      <nav className="lib__tabs" role="tablist" aria-label="Kitaplığın sırası">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id}
                  className={`lib__tab ${tab === id ? "is-on" : ""}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "alpha" && (
        <nav className="lib__alphabet" aria-label="Harfe git">
          {ALPHABET.map((l) => (
            <button key={l} type="button" disabled={!letters.has(l)} className="ed__rail-letter"
                    onClick={() => groupRefs.current[l]?.scrollIntoView({ behavior: "smooth", block: "start" })}>
              {l}
            </button>
          ))}
        </nav>
      )}

      <main className="lib__body">
        {projects && projects.length === 0 && (
          <p className="lib__empty">Henüz kitap yok. İlk PDF'inizi açılış sayfasına bıraktığınızda burada görünür.</p>
        )}
        {projects && projects.length > 0 && shown === 0 && (
          <p className="lib__empty">
            {tab === "read" && !q
              ? "Henüz Kindle'dan vurgu gelen bir kitap yok. Okuma Defteri'nden Kindle'ı bağladığınızda okuduklarınız burada toplanır."
              : "Aramaya uyan kitap yok."}
          </p>
        )}
        {groups.filter((g) => g.books.length).map((g) => (
          <section key={g.key} className="lib__group" ref={(el) => { if (g.letter) groupRefs.current[g.letter] = el; }}>
            {g.title && (
              <h2 className="lib__group-title">
                <span>{g.title}</span>
                <span className="lib__group-count">{g.books.length}</span>
              </h2>
            )}
            <ul className="lib__grid">
              {g.books.map((p) => (
                <ShelfCard key={p.session_id} p={p} index={index++} onOpen={onOpenProject} onRemoved={load} />
              ))}
            </ul>
          </section>
        ))}
      </main>
    </div>
  );
}
