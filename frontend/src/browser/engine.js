// Matbaa in the browser, the page's side (only in the build for the site,
// `vite build --mode browser`): start the engine (engine.worker.js), let the
// service worker (sw.js) reach it, and hand over a PDF the visitor dropped on
// the site's front page. See browser/ at the root of the repository.
//
// The app is on screen at once; the engine loads behind it. A request the
// app makes before the engine is up waits for it (in the worker), and the
// app shows how far the engine has come where a reader would look for it
// (EngineStatus.jsx).
import { useSyncExternalStore } from "react";

export const IN_BROWSER = import.meta.env.MODE === "browser";

const BASE = import.meta.env.BASE_URL;

export const STEPS = [
  ["download", "Tezgâh indiriliyor"],
  ["core", "Dizgi tezgâhı açılıyor"],
  ["packages", "Harfler kasaya diziliyor"],
  ["library", "Kitaplığınız açılıyor"],
  ["matbaa", "Matbaa hazırlanıyor"],
];

// What the app shows: the engine's step, the download's bytes, whether it
// is ready, or why it could not start (unsupported, busy, failed).
let state = { ready: !IN_BROWSER, step: null, bytes: null, problem: null, detail: null };
const listeners = new Set();

function update(patch) {
  state = { ...state, ...patch };
  listeners.forEach((listener) => listener());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useEngine() {
  return useSyncExternalStore(subscribe, () => state);
}

export function supported() {
  return "serviceWorker" in navigator && typeof Worker !== "undefined" && "indexedDB" in window
    && typeof WebAssembly === "object";
}

// Requests the service worker passes on. Listened for from the first moment,
// since a page it already controls can ask before the engine's worker exists;
// those wait here and go to the worker when it does.
let worker = null;
const early = [];

function passOn(event) {
  const msg = event.data;
  if (!msg || msg.kind !== "matbaa-api") return;
  const transfer = msg.body ? [event.ports[0], msg.body] : [event.ports[0]];
  if (worker) worker.postMessage(msg, transfer);
  else early.push([msg, transfer]);
}

if (IN_BROWSER && "serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("message", passOn);
}

// One tab at a time: two engines over one store would each write back their
// own copy of the books and lose the other's work.
function holdTheBench() {
  if (!navigator.locks) return Promise.resolve(true);
  return new Promise((resolve) => {
    navigator.locks.request("matbaa-tezgah", { ifAvailable: true }, (lock) => {
      resolve(Boolean(lock));
      return lock ? new Promise(() => {}) : undefined;
    });
  });
}

async function controlled() {
  await navigator.serviceWorker.register(`${BASE}sw.js`, { scope: BASE });
  await navigator.serviceWorker.ready;
  if (navigator.serviceWorker.controller) return;
  await new Promise((resolve) => navigator.serviceWorker.addEventListener("controllerchange", resolve, { once: true }));
}

function fail(code, detail) {
  update({ problem: code, detail: detail || null });
  return Object.assign(new Error(detail || code), { code });
}

// Resolves once the service worker answers this page and the engine's worker
// is there to take requests — a moment, not the download; the engine goes on
// loading after it. Started once, by main.jsx; api.js waits on it.
let wired = null;

export function startEngine() {
  if (!IN_BROWSER) return Promise.resolve();
  if (wired) return wired;
  wired = (async () => {
    if (!supported()) throw fail("unsupported");
    if (!(await holdTheBench())) throw fail("busy");
    await controlled();
    worker = new Worker(`${BASE}engine.worker.js`);
    worker.onmessage = (event) => {
      const msg = event.data || {};
      if (msg.kind === "progress") {
        update(msg.step === "download" && msg.detail ? { step: msg.step, bytes: msg.detail } : { step: msg.step });
      } else if (msg.kind === "ready") {
        update({ ready: true });
        // the books stay in this browser unless it runs short of room
        navigator.storage?.persist?.().catch(() => {});
      } else if (msg.kind === "failed") {
        fail("failed", msg.error);
      } else if (msg.kind === "save-failed") {
        console.warn("Matbaa: kitaplık kaydedilemedi", msg.error);
      }
    };
    worker.onerror = (event) => fail("failed", event.message || "worker");
    early.splice(0).forEach(([msg, transfer]) => worker.postMessage(msg, transfer));
    navigator.serviceWorker.startMessages?.();
    worker.postMessage({
      kind: "boot",
      config: { online: true, counterUrl: `${window.location.origin}/api/sayac` },
    });
  })();
  wired.catch((err) => console.error(err));
  return wired;
}

// A PDF dropped on the site's front page (site/site.js) waits in IndexedDB;
// it is taken out once, here.
export function takePendingPdf() {
  if (!new URLSearchParams(window.location.search).has("bekleyen")) return Promise.resolve(null);
  window.history.replaceState(null, "", window.location.pathname);
  return new Promise((resolve) => {
    const open = indexedDB.open("matbaa-bekleyen", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("pdf");
    open.onerror = () => resolve(null);
    open.onsuccess = () => {
      const db = open.result;
      const tx = db.transaction("pdf", "readwrite");
      const store = tx.objectStore("pdf");
      const get = store.get("bekleyen");
      get.onsuccess = () => {
        const item = get.result;
        store.delete("bekleyen");
        tx.oncomplete = () => {
          db.close();
          if (!item || !item.file) return resolve(null);
          resolve(new File([item.file], item.name || "kitap.pdf", { type: "application/pdf" }));
        };
      };
      get.onerror = () => { db.close(); resolve(null); };
    };
  });
}
