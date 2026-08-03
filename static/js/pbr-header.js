(function () {
  "use strict";

  var header = document.getElementById("pbr-app-header");
  if (!header) return;

  var lastScroll = 0;
  var ticking = false;

  function onScroll() {
    var y = window.scrollY || document.documentElement.scrollTop || 0;
    header.classList.toggle("app-header--scrolled", y > 8);
    var ae = document.activeElement;
    var typing =
      ae &&
      /^(INPUT|TEXTAREA|SELECT)$/i.test(ae.tagName) &&
      ae.type !== "checkbox" &&
      ae.type !== "radio";
    // Con el teclado abierto el scroll “salta”; no ocultar el header en ese momento.
    var hide = !typing && y > lastScroll && y > 120;
    header.classList.toggle("app-header--hide", hide);
    lastScroll = y;
    ticking = false;
  }

  window.addEventListener(
    "scroll",
    function () {
      if (!ticking) {
        window.requestAnimationFrame(onScroll);
        ticking = true;
      }
    },
    { passive: true }
  );

  onScroll();
})();
