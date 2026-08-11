/**
 * Barra de progreso de carga del sistema PBR.
 */
(function () {
  "use strict";

  var loader = document.getElementById("pbr-system-loader");
  var fill = document.getElementById("pbr-system-loader-fill");
  var pctEl = document.getElementById("pbr-system-loader-pct");
  if (!loader || !fill) return;

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var done = false;
  var progress = 0;
  var rafId = null;

  document.body.classList.add("pbr-loader-active");

  var isMobile =
    document.documentElement.getAttribute("data-pbr-class") === "mobile" ||
    document.documentElement.getAttribute("data-pbr-view") === "phone";

  function setProgress(p) {
    progress = Math.min(100, Math.max(0, p));
    fill.style.width = progress + "%";
    if (pctEl) pctEl.textContent = Math.round(progress) + "%";
  }

  function finish() {
    if (done) return;
    done = true;
    if (rafId) cancelAnimationFrame(rafId);
    setProgress(100);
    loader.classList.add("pbr-system-loader--done");
    document.body.classList.remove("pbr-loader-active");
    window.setTimeout(function () {
      loader.remove();
    }, reduce ? 120 : 480);
  }

  if (reduce || isMobile) {
    setProgress(100);
    window.setTimeout(finish, isMobile ? 280 : 200);
    return;
  }

  var start = performance.now();
  var duration = 2400;

  function tick(now) {
    if (done) return;
    var elapsed = now - start;
    var t = Math.min(1, elapsed / duration);
    var eased = 1 - Math.pow(1 - t, 2.4);
    var target = eased * 90;
    if (document.readyState === "complete" && t > 0.4) {
      target = Math.max(target, 85 + (t - 0.4) * 28);
    }
    setProgress(target);
    if (t < 1) {
      rafId = requestAnimationFrame(tick);
    }
  }

  rafId = requestAnimationFrame(tick);

  window.addEventListener("load", function () {
    setProgress(Math.max(progress, 96));
    window.setTimeout(finish, 520);
  });

  window.setTimeout(function () {
    if (!done) finish();
  }, 4800);
})();
