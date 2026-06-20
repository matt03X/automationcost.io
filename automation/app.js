/* ============================================================================
   AutomationCost — shared chrome behaviour (app.js)
   Ported from the WizardCost homepage: scroll-reveal (.rv → .in) with a
   fail-safe, scroll progress bar (#ac-progress), nav condense (.ac-nav.scrolled)
   and the "More" dropdown toggle. Every block guards on element presence so it
   is harmless on pages that haven't opted into the new chrome yet.
   ========================================================================== */
(function () {
  "use strict";
  var reduced = matchMedia("(prefers-reduced-motion:reduce)").matches;
  if (reduced) document.body.classList.remove("anim");

  /* ── scroll reveal (+ fail-safe so content never stays hidden) ─────────── */
  var revealed = false;
  var rvEls = document.querySelectorAll(".rv");
  if (rvEls.length && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      revealed = true;
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.16 });
    rvEls.forEach(function (el) { io.observe(el); });
    /* fallback: if the observer never fired (sandboxed iframe etc.), reveal all */
    setTimeout(function () {
      if (revealed) return;
      rvEls.forEach(function (el) { el.classList.add("in"); });
    }, 600);
  } else {
    rvEls.forEach(function (el) { el.classList.add("in"); });
  }

  /* ── scroll progress bar + nav condense ────────────────────────────────── */
  var prog = document.getElementById("ac-progress");
  var nav = document.querySelector(".ac-nav");
  function onScroll() {
    var h = document.documentElement;
    var max = h.scrollHeight - h.clientHeight;
    if (prog) prog.style.width = (max > 0 ? (h.scrollTop / max * 100) : 0) + "%";
    if (nav) nav.classList.toggle("scrolled", h.scrollTop > 40);
  }
  if (prog || nav) {
    addEventListener("scroll", onScroll, { passive: true });
    addEventListener("resize", onScroll);
    onScroll();
  }

  /* ── dropdowns ("More" + language switcher) ─────────────────────────────
     Wires every .ac-dd on the page (there can be two: More + globe), closing
     the others when one opens. Backward-compatible with a single dropdown. */
  var dds = document.querySelectorAll(".ac-dd");
  if (dds.length) {
    function closeDd(dd) {
      dd.classList.remove("open");
      var b = dd.querySelector(".ac-dd-btn");
      if (b) b.setAttribute("aria-expanded", "false");
    }
    dds.forEach(function (dd) {
      var btn = dd.querySelector(".ac-dd-btn");
      var menu = dd.querySelector(".ac-dd-menu");
      if (!btn || !menu) return;
      dd._place = function () {
        var r = btn.getBoundingClientRect();
        menu.style.left = Math.max(8, Math.min(r.right - menu.offsetWidth, window.innerWidth - menu.offsetWidth - 8)) + "px";
        menu.style.top = (r.bottom + 10) + "px";
      };
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        dds.forEach(function (o) { if (o !== dd) closeDd(o); });
        var open = dd.classList.toggle("open");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        if (open) dd._place();
      });
    });
    addEventListener("click", function (e) {
      dds.forEach(function (dd) { if (dd.classList.contains("open") && !dd.contains(e.target)) closeDd(dd); });
    });
    addEventListener("keydown", function (e) {
      if (e.key === "Escape") dds.forEach(closeDd);
    });
    addEventListener("resize", function () {
      dds.forEach(function (dd) { if (dd.classList.contains("open") && dd._place) dd._place(); });
    });
  }
})();
