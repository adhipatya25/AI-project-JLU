/* ScoutIQ Django - shared on every page: theme toggle, 3D tilt, hero parallax,
 * reveal-on-scroll (verbatim from the FastAPI frontend) + history table. */

/* ---------- bright/dark theme toggle ---------- */
(function initTheme() {
  const root = document.documentElement;
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const icon = document.getElementById("theme-icon");
  const label = document.getElementById("theme-label");
  const stored = localStorage.getItem("scoutiq-theme");
  // Bright FIFA theme is the default (faculty requirement).
  if (stored === "dark" || stored === "light") {
    root.setAttribute("data-theme", stored);
  }
  function sync() {
    const dark = root.getAttribute("data-theme") === "dark";
    btn.setAttribute("aria-pressed", String(dark));
    icon.textContent = dark ? "☀" : "◐";
    label.textContent = dark ? "Bright" : "Dark";
  }
  btn.addEventListener("click", () => {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    localStorage.setItem("scoutiq-theme", next);
    sync();
  });
  sync();
})();

/* ---------- 3D tilt cards (pointer-driven, respects reduced motion) ---------- */
(function initTilt() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.querySelectorAll(".tilt").forEach((card) => {
    let raf = null;
    card.addEventListener("pointermove", (e) => {
      const r = card.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        card.style.transform = `perspective(900px) rotateX(${(-py * 7).toFixed(2)}deg) rotateY(${(px * 9).toFixed(2)}deg) translateY(-3px)`;
      });
    });
    card.addEventListener("pointerleave", () => {
      if (raf) cancelAnimationFrame(raf);
      card.style.transform = "";
    });
  });
})();

/* ---------- reveal on scroll + animated counters ---------- */
(function initReveal() {
  const els = document.querySelectorAll("[data-reveal]");
  const counters = document.querySelectorAll("[data-count]");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!("IntersectionObserver" in window) || reduced) {
    els.forEach((el) => el.classList.add("in"));
    return;
  }
  const cio = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (!en.isIntersecting) return;
      const el = en.target;
      const target = Number(el.getAttribute("data-count")) || 0;
      const t0 = performance.now();
      const dur = 900;
      (function tick(t) {
        const p = Math.min((t - t0) / dur, 1);
        el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(tick);
      })(t0);
      cio.unobserve(el);
    });
  }, { threshold: 0.4 });
  counters.forEach((el) => cio.observe(el));
  const rio = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (en.isIntersecting) {
        en.target.classList.add("in");
        rio.unobserve(en.target);
      }
    });
  }, { threshold: 0.12 });
  els.forEach((el) => rio.observe(el));
})();

/* ---------- prediction history (Django REST API) ---------- */
(function () {
  /* --- history page: fetch rows from the DRF API, with filters + errors --- */
  const body = document.getElementById("history-body");
  if (body) {
    const status = document.getElementById("api-status");
    const fPos = document.getElementById("f-position");
    const fRating = document.getElementById("f-rating");
    const fSearch = document.getElementById("f-search");
    let timer = null;

    function say(msg, err) {
      if (!status) return;
      status.textContent = msg;
      status.classList.toggle("is-error", !!err);
    }

    async function load() {
      const q = new URLSearchParams();
      if (fPos.value) q.set("position", fPos.value);
      if (fRating.value) q.set("rating", fRating.value);
      if (fSearch.value.trim()) q.set("search", fSearch.value.trim());
      say("Loading from /api/predictions/ …");
      try {
        const res = await fetch("/api/predictions/?" + q.toString(), { headers: { Accept: "application/json" } });
        if (res.status === 403 || res.status === 401) throw new Error("Logged out? Log in again to use the API.");
        if (!res.ok) throw new Error("API returned HTTP " + res.status + ".");
        const data = await res.json();
        const rows = data.results || data;
        body.replaceChildren();
        if (!rows.length) {
          const tr = document.createElement("tr");
          tr.innerHTML = '<td colspan="6" class="muted">No predictions stored yet — predict one first.</td>';
          body.appendChild(tr);
        }
        rows.forEach((r) => {
          const p = r.player || {};
          const tr = document.createElement("tr");
          const link = document.createElement("a");
          link.href = "/players/" + p.id + "/";
          link.textContent = p.name || ("#" + p.id);
          const c0 = document.createElement("td"); c0.appendChild(link);
          tr.appendChild(c0);
          [[p.position + " · " + (p.sub_position || "")], [r.predicted_rating, true], [(r.predicted_by_name || "—")], [(r.created_at || "").slice(0, 10)]].forEach(([txt, pill]) => {
            const td = document.createElement("td");
            if (pill) {
              const s = document.createElement("span");
              s.className = "csv-pill csv-" + txt;
              s.textContent = txt;
              td.appendChild(s);
            } else td.textContent = txt;
            tr.appendChild(td);
          });
          // detail link cell
          const td = document.createElement("td");
          const a = document.createElement("a");
          a.href = "/players/" + p.id + "/";
          a.textContent = "Open →";
          td.appendChild(a);
          tr.appendChild(td);
          body.appendChild(tr);
        });
        say("Showing " + rows.length + " prediction(s).");
      } catch (e) {
        body.replaceChildren();
        say(e.message.includes("Failed to fetch") ? "Cannot reach the server. Is runserver still running?" : e.message, true);
      }
    }

    [fPos, fRating].forEach((el) => el.addEventListener("change", load));
    fSearch.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 350); });
    load();
  }
})();
