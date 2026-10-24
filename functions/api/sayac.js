// The site's counter (Cloudflare Pages Function, D1 database bound as DB).
//
// POST /api/sayac  {"tur": "felsefe", "v": 1}
//   One book set by a reader's Matbaa (backend/app/counter.py). The genre
//   must be one Matbaa knows; nothing else is read from the request and the
//   sender's address is not stored: a row is the genre, the day and the hour.
//   A daily ceiling keeps a stuck or hostile sender from running it up.
//
// GET /api/sayac
//   {"total": 15, "genres": [{"tur": "felsefe", "n": 4}, ...],
//    "recent": [{"tur": "felsefe", "saat": "2026-10-24T09"}, ...]}
//   for the front page; cached a minute.

const GENRES = new Set([
  "felsefe", "siyaset", "ekonomi", "tarih", "sosyoloji", "psikoloji", "sanat", "bilim",
  "kisisel", "din", "turk-edebiyati", "rus-edebiyati", "dunya-edebiyati", "diger",
]);
const MAX_BODY = 64;
const DAILY_CAP = 2000;
const RECENT = 20;

function reply(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

export async function onRequestPost({ request, env }) {
  const text = await request.text();
  if (text.length > MAX_BODY) return reply({ error: "too large" }, 413);
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return reply({ error: "not JSON" }, 400);
  }
  if (!body || !GENRES.has(body.tur)) return reply({ error: "unknown genre" }, 400);

  const now = new Date().toISOString();
  const day = now.slice(0, 10);
  const today = await env.DB.prepare("SELECT COUNT(*) AS n FROM dizilen WHERE gun = ?").bind(day).first();
  if (today && today.n >= DAILY_CAP) return reply({ error: "daily limit" }, 429);
  await env.DB.prepare("INSERT INTO dizilen (tur, gun, saat) VALUES (?, ?, ?)")
    .bind(body.tur, day, now.slice(0, 13)).run();
  return reply({ ok: true }, 201);
}

export async function onRequestGet({ env }) {
  const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM dizilen").first();
  const genres = await env.DB.prepare("SELECT tur, COUNT(*) AS n FROM dizilen GROUP BY tur ORDER BY n DESC, tur").all();
  const recent = await env.DB.prepare("SELECT tur, saat FROM dizilen ORDER BY id DESC LIMIT ?").bind(RECENT).all();
  return reply(
    { total: total ? total.n : 0, genres: genres.results || [], recent: recent.results || [] },
    200,
    { "Cache-Control": "public, max-age=60" },
  );
}
