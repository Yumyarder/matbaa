// The site's script: the way into the app on the front page (a PDF dropped
// on the red block), and the counter (functions/api/sayac.js) on two pages.
//
// The front page (#sayac): how many books every reader's Matbaa has set,
// counting up when it comes into view; clicked, the genres open beneath it
// as a ledger, a tally mark a book and the fifth struck in red, with the
// latest books and a way to the shelf. At zero it says so and invites the
// first book.
//
// The shelf page (#raf, dizilenler.html): every book set as a cloth spine on
// a shelf, its colour and band telling its genre, then the ledger and the
// latest books.
//
// Built with DOM nodes and text only; when the counter cannot be read the
// front page's section stays hidden and the shelf page says so.
(function () {
  "use strict";
  var LABELS = {
    "felsefe": "Felsefe", "siyaset": "Siyaset", "ekonomi": "Ekonomi", "tarih": "Tarih",
    "sosyoloji": "Sosyoloji", "psikoloji": "Psikoloji", "sanat": "Sanat ve mimari", "bilim": "Bilim",
    "kisisel": "Kişisel gelişim", "din": "Din ve mitoloji", "turk-edebiyati": "Türk edebiyatı",
    "rus-edebiyati": "Rus edebiyatı", "dunya-edebiyati": "Dünya edebiyatı", "diger": "Diğer"
  };
  // a genre's cloth and band, as on the app's cloth-bound books
  var CLOTH = {
    "felsefe": ["iron", "red"], "siyaset": ["rubric", "bone"], "ekonomi": ["chalk", "iron"],
    "tarih": ["bone", "iron"], "sosyoloji": ["chalk", "red"], "psikoloji": ["rubric", "iron"],
    "sanat": ["iron", "bone"], "bilim": ["chalk", "rubric"], "kisisel": ["bone", "rubric"],
    "din": ["iron", "chalk"], "turk-edebiyati": ["bone", "red"], "rus-edebiyati": ["rubric", "chalk"],
    "dunya-edebiyati": ["chalk", "bone"], "diger": ["bone", "chalk"]
  };
  var SVG = "http://www.w3.org/2000/svg";
  var MAX_MARKS = 25;
  var MAX_SPINES = 160;
  var label = function (id) { return LABELS[id] || "Diğer"; };
  var fmt = function (n) { return n.toLocaleString("tr-TR"); };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function line(x1, y1, x2, y2, cls) {
    var l = document.createElementNS(SVG, "line");
    l.setAttribute("x1", x1); l.setAttribute("y1", y1); l.setAttribute("x2", x2); l.setAttribute("y2", y2);
    l.setAttribute("class", cls);
    return l;
  }

  function tally(n) {
    var groups = Math.ceil(n / 5), width = Math.max(groups * 24, 4);
    var svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "tally__marks");
    svg.setAttribute("width", width); svg.setAttribute("height", "18");
    svg.setAttribute("viewBox", "0 0 " + width + " 18");
    svg.setAttribute("aria-hidden", "true");
    for (var g = 0; g < groups; g++) {
      var k = Math.min(5, n - g * 5), x0 = g * 24;
      for (var j = 0; j < Math.min(k, 4); j++) svg.appendChild(line(x0 + 2 + j * 4.5, 2, x0 + 2 + j * 4.5, 16, "tally__mark"));
      if (k === 5) svg.appendChild(line(x0, 14, x0 + 18, 4, "tally__strike"));
    }
    return svg;
  }

  function when(hour) {
    var t = Date.parse(hour + ":00:00Z");
    if (isNaN(t)) return "";
    var then = new Date(t), now = new Date();
    var days = Math.round((new Date(now.toDateString()) - new Date(then.toDateString())) / 86400000);
    if (days === 0) {
      var h = then.getHours();
      return h < 5 ? "bu gece" : h < 12 ? "bu sabah" : h < 18 ? "bugün öğleden sonra" : "bu akşam";
    }
    return days === 1 ? "dün" : days + " gün önce";
  }

  function countUp(node, target) {
    if (!target || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) {
      node.textContent = fmt(target);
      return;
    }
    var start = null;
    function step(now) {
      if (start === null) start = now;
      var p = Math.min(1, (now - start) / 1200);
      node.textContent = fmt(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function whenSeen(node, fn) {
    if (!("IntersectionObserver" in window)) { fn(); return; }
    var seen = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) { seen.disconnect(); fn(); }
    }, { threshold: 0.6 });
    seen.observe(node);
  }

  function ledger(rows, genres) {
    var most = Math.max.apply(null, [1].concat(genres.map(function (g) { return g.n; })));
    genres.forEach(function (g) {
      var li = el("li", "tally__row");
      li.appendChild(el("span", "tally__genre", label(g.tur)));
      if (most <= MAX_MARKS) {
        li.appendChild(tally(g.n));
      } else {
        var bar = el("span", "tally__bar"), fill = el("span");
        fill.style.width = (100 * g.n / most) + "%";
        bar.appendChild(fill);
        li.appendChild(bar);
      }
      li.appendChild(el("span", "tally__k", fmt(g.n)));
      rows.appendChild(li);
    });
  }

  function latestLine(recent, count) {
    var latest = recent.slice(0, count).map(function (r) { return label(r.tur) + ", " + when(r.saat); });
    return latest.length ? "Son dizilenler: " + latest.join("; ") + "." : "";
  }

  // --- the front page -------------------------------------------------------
  function front(box, data) {
    var number = box.querySelector(".tally__n");
    var button = box.querySelector(".tally__count"), sheet = box.querySelector(".tally__ledger");
    if (data.total === 0) {
      box.querySelector(".tally__latest").textContent = "Henüz kitap dizilmedi. İlk kitabı sen diz.";
      sheet.hidden = false;
      button.setAttribute("aria-expanded", "true");
      button.disabled = true;
    } else {
      ledger(box.querySelector(".tally__rows"), data.genres);
      box.querySelector(".tally__latest").textContent = latestLine(data.recent, 3);
      button.addEventListener("click", function () {
        var open = button.getAttribute("aria-expanded") !== "true";
        button.setAttribute("aria-expanded", String(open));
        sheet.hidden = !open;
      });
    }
    box.hidden = false;
    whenSeen(number, function () { countUp(number, data.total); });
  }

  // --- the shelf page ---------------------------------------------------------
  function hash(i) {
    var x = Math.sin(i * 12.9898 + 78.233) * 43758.5453;
    return x - Math.floor(x);
  }

  function shelf(page, data) {
    var number = page.querySelector(".raf__n");
    whenSeen(number, function () { countUp(number, data.total); });
    if (data.total === 0) {
      page.querySelector(".raf__empty").hidden = false;
      return;
    }
    // one spine a book, genres taking turns the way books come off the press
    var left = {}, order = [];
    data.genres.forEach(function (g) { left[g.tur] = g.n; });
    var shown = Math.min(data.total, MAX_SPINES);
    while (order.length < shown) {
      var progressed = false;
      data.genres.forEach(function (g) {
        if (order.length < shown && left[g.tur] > 0) { order.push(g.tur); left[g.tur] -= 1; progressed = true; }
      });
      if (!progressed) break;
    }
    var spines = order.map(function (tur, i) {
      var cloth = CLOTH[tur] || CLOTH.diger;
      var spine = el("span", "spine spine--" + cloth[0] + " band--" + cloth[1]);
      var rem = 1.15 + hash(i) * 0.75;
      spine.style.width = rem.toFixed(2) + "rem";
      spine.style.height = (9.5 + hash(i + 97) * 3.5).toFixed(2) + "rem";
      spine.title = label(tur);
      spine.appendChild(el("span", "spine__band"));
      return { node: spine, rem: rem };
    });
    // as many spines to a shelf as its width takes, each shelf with its board
    // (measured once the section is shown: hidden, it has no width)
    page.querySelector(".raf__filled").hidden = false;
    var shelves = page.querySelector(".raf__spines");
    function arrange() {
      var unit = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      var room = shelves.clientWidth - 8, used = 0, row = null;
      shelves.textContent = "";
      spines.forEach(function (s) {
        var w = s.rem * unit + 0.3 * unit;
        if (!row || used + w > room) { row = el("div", "raf__row"); shelves.appendChild(row); used = 0; }
        row.appendChild(s.node);
        used += w;
      });
    }
    arrange();
    var pending = null;
    window.addEventListener("resize", function () {
      clearTimeout(pending);
      pending = setTimeout(arrange, 150);
    });
    if (data.total > shown) {
      page.querySelector(".raf__more").textContent = "ve " + fmt(data.total - shown) + " kitap daha";
    }
    var legend = page.querySelector(".raf__legend");
    data.genres.forEach(function (g) {
      var cloth = CLOTH[g.tur] || CLOTH.diger;
      var item = el("li", "raf__key");
      var swatch = el("span", "spine spine--" + cloth[0] + " band--" + cloth[1] + " spine--swatch");
      swatch.appendChild(el("span", "spine__band"));
      item.appendChild(swatch);
      item.appendChild(el("span", "raf__key-name", label(g.tur)));
      item.appendChild(el("span", "raf__key-n", fmt(g.n)));
      legend.appendChild(item);
    });
    ledger(page.querySelector(".tally__rows"), data.genres);
    var recent = page.querySelector(".raf__recent");
    data.recent.forEach(function (r) {
      var li = el("li");
      li.appendChild(el("span", "raf__recent-genre", label(r.tur)));
      li.appendChild(el("span", "raf__recent-when", when(r.saat)));
      recent.appendChild(li);
    });
    page.querySelector(".raf__filled").hidden = false;
  }

  // --- the way in -------------------------------------------------------------
  // A PDF dropped on the block waits in this browser's IndexedDB for the app
  // (uygulama/, the same origin), which opens with it; it is never sent.
  function stash(file) {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) { reject(new Error("no IndexedDB")); return; }
      var open = indexedDB.open("matbaa-bekleyen", 1);
      open.onupgradeneeded = function () { open.result.createObjectStore("pdf"); };
      open.onerror = function () { reject(open.error); };
      open.onsuccess = function () {
        var db = open.result, tx = db.transaction("pdf", "readwrite");
        tx.objectStore("pdf").put({ name: file.name, file: file, at: Date.now() }, "bekleyen");
        tx.oncomplete = function () { db.close(); resolve(); };
        tx.onerror = function () { db.close(); reject(tx.error); };
      };
    });
  }

  function startPanel(link) {
    var status = document.querySelector(".start__status"), depth = 0;
    var hasFiles = function (e) {
      return !!e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0;
    };
    var leave = function () { depth = 0; link.classList.remove("start--over"); };
    link.addEventListener("dragenter", function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth += 1;
      link.classList.add("start--over");
    });
    link.addEventListener("dragleave", function () {
      depth = Math.max(0, depth - 1);
      if (!depth) link.classList.remove("start--over");
    });
    // anywhere on the page a dropped file must not replace the page itself
    window.addEventListener("dragover", function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = link.contains(e.target) ? "copy" : "none";
    });
    window.addEventListener("drop", function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      leave();
      if (!link.contains(e.target)) {
        status.textContent = "PDF'i kırmızı kutunun üstüne bırakın.";
        return;
      }
      var file = e.dataTransfer.files[0];
      if (!file || (file.type !== "application/pdf" && !/\.pdf$/i.test(file.name))) {
        status.textContent = "Bu bir PDF değil. Matbaa PDF dosyalarını dizer.";
        return;
      }
      status.textContent = "Tezgâh açılıyor…";
      var target = link.getAttribute("href");
      stash(file).then(function () { window.location.href = target + "?bekleyen=1"; },
                       function () { window.location.href = target; });
    });
  }

  var start = document.getElementById("baslat");
  if (start) startPanel(start);

  var box = document.getElementById("sayac");
  var page = document.getElementById("raf");
  if ((!box && !page) || !window.fetch) return;
  fetch("/api/sayac", { headers: { "Accept": "application/json" } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data || typeof data.total !== "number" || !Array.isArray(data.genres)) throw new Error("no counter");
      if (box) front(box, data);
      if (page) shelf(page, data);
    })
    .catch(function () {
      if (page) page.querySelector(".raf__error").hidden = false;
    });
})();
