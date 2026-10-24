// The counter on the front page: how many books every reader's Matbaa has
// set (functions/api/sayac.js), counting up when it comes into view.
// Clicked, the genres open beneath it as a ledger, a tally mark a book and
// the fifth struck in red, with the latest books set. Built with DOM nodes
// and text only; when the counter cannot be read the section stays hidden.
(function () {
  "use strict";
  var box = document.getElementById("sayac");
  if (!box || !window.fetch) return;
  var LABELS = {
    "felsefe": "Felsefe", "siyaset": "Siyaset", "ekonomi": "Ekonomi", "tarih": "Tarih",
    "sosyoloji": "Sosyoloji", "psikoloji": "Psikoloji", "sanat": "Sanat ve mimari", "bilim": "Bilim",
    "kisisel": "Kişisel gelişim", "din": "Din ve mitoloji", "turk-edebiyati": "Türk edebiyatı",
    "rus-edebiyati": "Rus edebiyatı", "dunya-edebiyati": "Dünya edebiyatı", "diger": "Diğer"
  };
  var SVG = "http://www.w3.org/2000/svg";
  var MAX_MARKS = 25;
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
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
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

  function render(data) {
    var rows = box.querySelector(".tally__rows");
    var most = Math.max.apply(null, [1].concat(data.genres.map(function (g) { return g.n; })));
    data.genres.forEach(function (g) {
      var li = el("li", "tally__row");
      li.appendChild(el("span", "tally__genre", LABELS[g.tur] || "Diğer"));
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
    var latest = data.recent.slice(0, 3).map(function (r) { return (LABELS[r.tur] || "Diğer") + ", " + when(r.saat); });
    box.querySelector(".tally__latest").textContent = latest.length ? "Son dizilenler: " + latest.join("; ") + "." : "";

    var button = box.querySelector(".tally__count"), ledger = box.querySelector(".tally__ledger");
    button.addEventListener("click", function () {
      var open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      ledger.hidden = !open;
    });
    box.hidden = false;

    var number = box.querySelector(".tally__n");
    if ("IntersectionObserver" in window) {
      var seen = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) { seen.disconnect(); countUp(number, data.total); }
      }, { threshold: 0.6 });
      seen.observe(number);
    } else {
      number.textContent = fmt(data.total);
    }
  }

  fetch("/api/sayac", { headers: { "Accept": "application/json" } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (data && typeof data.total === "number" && data.total > 0 && Array.isArray(data.genres)) render(data);
    })
    .catch(function () {});
})();
