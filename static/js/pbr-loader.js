/**
 * Barra de progreso de arranque del sistema PBR (splash).
 */
(function () {
  "use strict";

  var loader = document.getElementById("pbr-system-loader");
  var fill = document.getElementById("pbr-system-loader-fill");
  var pctEl = document.getElementById("pbr-system-loader-pct");
  var statusEl = document.getElementById("pbr-system-loader-status");
  var stepsEl = document.getElementById("pbr-system-loader-steps");
  if (!loader || !fill) return;

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var done = false;
  var progress = 0;
  var rafId = null;

  var isMobile =
    document.documentElement.getAttribute("data-pbr-class") === "mobile" ||
    document.documentElement.getAttribute("data-pbr-view") === "phone";

  var PHASES = [
    { at: 0, msg: "Iniciando sistema…", step: 0 },
    { at: 18, msg: "Cargando interfaz…", step: 1 },
    { at: 42, msg: "Preparando módulos…", step: 2 },
    { at: 68, msg: "Sincronizando recursos…", step: 3 },
    { at: 88, msg: "Casi listo…", step: 4 },
    { at: 100, msg: "Bienvenido", step: 4 },
  ];

  document.body.classList.add("pbr-loader-active");

  function phaseFor(p) {
    var cur = PHASES[0];
    for (var i = 0; i < PHASES.length; i++) {
      if (p >= PHASES[i].at) cur = PHASES[i];
    }
    return cur;
  }

  function updateSteps(stepIdx) {
    if (!stepsEl) return;
    var steps = stepsEl.querySelectorAll(".pbr-system-loader__step");
    for (var i = 0; i < steps.length; i++) {
      steps[i].classList.toggle("is-done", i < stepIdx);
      steps[i].classList.toggle("is-active", i === stepIdx);
    }
  }

  function setProgress(p) {
    progress = Math.min(100, Math.max(progress, p));
    fill.style.width = progress + "%";
    if (pctEl) pctEl.textContent = Math.round(progress) + "%";
    var ph = phaseFor(progress);
    if (statusEl && ph.msg) statusEl.textContent = ph.msg;
    updateSteps(ph.step);
    if (window.pbrProgress && typeof window.pbrProgress.set === "function") {
      window.pbrProgress.set(Math.min(99, progress * 0.35));
    }
  }

  function finish() {
    if (done) return;
    done = true;
    if (rafId) cancelAnimationFrame(rafId);
    setProgress(100);
    loader.classList.add("pbr-system-loader--done");
    document.body.classList.remove("pbr-loader-active");
    if (window.pbrProgress && typeof window.pbrProgress.done === "function") {
      window.pbrProgress.done(true);
    }
    window.setTimeout(function () {
      if (loader.parentNode) loader.parentNode.removeChild(loader);
    }, reduce ? 120 : 520);
  }

  /* Móvil: splash completo oculto por CSS; solo barra superior ligera. */
  if (isMobile) {
    document.body.classList.remove("pbr-loader-active");
    loader.classList.add("pbr-system-loader--mobile-skip");
    if (window.pbrProgress && typeof window.pbrProgress.start === "function") {
      window.pbrProgress.start("Cargando…");
      window.pbrProgress.set(35);
    }
    var mobileStart = performance.now();
    function mobileTick(now) {
      if (done) return;
      var t = Math.min(1, (now - mobileStart) / 900);
      setProgress(t * 85);
      if (window.pbrProgress) window.pbrProgress.set(35 + t * 55);
      if (t < 1) rafId = requestAnimationFrame(mobileTick);
    }
    rafId = requestAnimationFrame(mobileTick);
    window.addEventListener(
      "load",
      function () {
        setProgress(100);
        window.setTimeout(finish, 180);
      },
      { once: true }
    );
    window.setTimeout(finish, 2200);
    return;
  }

  if (reduce) {
    setProgress(100);
    window.setTimeout(finish, 220);
    return;
  }

  var start = performance.now();
  var duration = 2600;

  function tick(now) {
    if (done) return;
    var elapsed = now - start;
    var t = Math.min(1, elapsed / duration);
    var eased = 1 - Math.pow(1 - t, 2.6);
    var target = eased * 88;
    if (document.readyState === "interactive") {
      target = Math.max(target, 42);
    }
    if (document.readyState === "complete" && t > 0.35) {
      target = Math.max(target, 78 + (t - 0.35) * 22);
    }
    setProgress(target);
    if (t < 1) rafId = requestAnimationFrame(tick);
  }

  document.addEventListener(
    "DOMContentLoaded",
    function () {
      setProgress(Math.max(progress, 38));
    },
    { once: true }
  );

  rafId = requestAnimationFrame(tick);

  window.addEventListener(
    "load",
    function () {
      setProgress(Math.max(progress, 96));
      window.setTimeout(finish, 480);
    },
    { once: true }
  );

  window.setTimeout(function () {
    if (!done) finish();
  }, 5200);
})();
