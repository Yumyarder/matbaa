// Runs functions/api/sayac.js against an in-memory SQLite standing in for
// Cloudflare D1 (node:sqlite), with the real schema, and prints what each
// request answered as JSON for tools/test_counter.py to judge.
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const db = new DatabaseSync(":memory:");
db.exec(readFileSync(path.join(root, "functions", "schema.sql"), "utf8"));

// the slice of the D1 binding the function uses
const DB = {
  prepare(sql) {
    const make = (args) => ({
      bind: (...a) => make(a),
      first: async () => db.prepare(sql).get(...args) ?? null,
      all: async () => ({ results: db.prepare(sql).all(...args) }),
      run: async () => { db.prepare(sql).run(...args); return { success: true }; },
    });
    return make([]);
  },
};
const fn = await import(pathToFileURL(path.join(root, "functions", "api", "sayac.js")).href);
const post = async (body) => {
  const res = await fn.onRequestPost({ request: new Request("https://x/api/sayac", { method: "POST", body }), env: { DB } });
  return res.status;
};

const out = {};
out.valid = await post(JSON.stringify({ tur: "felsefe", v: 1 }));
await post(JSON.stringify({ tur: "felsefe", v: 1 }));
await post(JSON.stringify({ tur: "rus-edebiyati", v: 1 }));
out.extraIgnored = await post(JSON.stringify({ tur: "siyaset", ad: "Devlet ve Devrim" }));
out.unknown = await post(JSON.stringify({ tur: "uydurma", v: 1 }));
out.notJson = await post("tur=felsefe");
out.tooLarge = await post(JSON.stringify({ tur: "felsefe", pad: "x".repeat(80) }));
out.columns = db.prepare("SELECT name FROM pragma_table_info('dizilen')").all().map((r) => r.name);
const get = await fn.onRequestGet({ env: { DB } });
out.get = { status: get.status, cache: get.headers.get("Cache-Control"), body: await get.json() };
const day = new Date().toISOString().slice(0, 10);
const fill = db.prepare("INSERT INTO dizilen (tur, gun, saat) VALUES ('diger', ?, ?)");
for (let i = 0; i < 2000; i++) fill.run(day, `${day}T00`);
out.overDailyLimit = await post(JSON.stringify({ tur: "felsefe", v: 1 }));
console.log(JSON.stringify(out));
