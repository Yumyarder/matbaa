// Matbaa in the browser, the page's side (only in the build for the site,
// `vite build --mode browser`): start the engine (engine.worker.js), let the
// service worker (sw.js) reach it, and hand over a PDF the visitor dropped on
// the site's front page. See browser/ at the root of the repository.

export const IN_BROWSER = import.meta.env.MODE === "browser";

const BASE = import.meta.env.BASE_URL;

export const STEPS = [
  ["download", "Tezgâh indiriliyor"],
  ["core", "Dizgi tezgâhı açılıyor"],
  ["packages", "Harfler kasaya diziliyor"],
  ["library", "Kitaplığınız açılıyor"],
  ["matbaa", "Matbaa hazırlanıyor"],
];

export function supported() {
  return "serviceWorker" in navigator && typeof Worker !== "undefined" && "indexedDB" in window
    && typeof WebAssembly === "object";
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

export async function startEngine(onStep) {
  if (!supported()) throw Object.assign(new Error("unsupported"), { code: "unsupported" });
  if (!(await holdTheBench())) throw Object.assign(new Error("busy"), { code: "busy" });
  await controlled();
  const worker = new Worker(`${BASE}engine.worker.js`);
  // Requests the service worker passes on; registered before anything asks.
  navigator.serviceWorker.addEventListener("message", (event) => {
    const msg = event.data;
    if (!msg || msg.kind !== "matbaa-api") return;
    worker.postMessage(msg, msg.body ? [event.ports[0], msg.body] : [event.ports[0]]);
  });
  navigator.serviceWorker.startMessages?.();
  await new Promise((resolve, reject) => {
    worker.onmessage = (event) => {
      const msg = event.data || {};
      if (msg.kind === "progress") onStep?.(msg.step, msg.detail);
      else if (msg.kind === "ready") resolve();
      else if (msg.kind === "failed") reject(Object.assign(new Error(msg.error), { code: "failed" }));
      else if (msg.kind === "save-failed") console.warn("Matbaa: kitaplık kaydedilemedi", msg.error);
    };
    worker.onerror = (event) => reject(Object.assign(new Error(event.message || "worker"), { code: "failed" }));
    worker.postMessage({
      kind: "boot",
      config: { online: true, counterUrl: `${window.location.origin}/api/sayac` },
    });
  });
  // the books stay in this browser unless it runs short of room
  navigator.storage?.persist?.().catch(() => {});
  return worker;
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
