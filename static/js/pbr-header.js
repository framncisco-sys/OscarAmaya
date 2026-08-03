(function () {
  "use strict";

  var header = document.getElementById("pbr-app-header");
  if (!header) return;

  function isMobileClass() {
    var c = document.documentElement.getAttribute("data-pbr-class") || "";
    var view = document.documentElement.getAttribute("data-pbr-view") || "";
    return c === "mobile" || view === "phone" || view === "tablet";
  }

  // En móvil el header es fijo en el shell: no ocultar ni cambiar tamaño.
  if (isMobileClass()) {
    header.classList.remove("app-header--hide", "app-header--scrolled");
    return;
  }

  var lastScroll = 0;
  var ticking = false;

  function onScroll() {
    if (isMobileClass()) {
      header.classList.remove("app-header--hide", "app-header--scrolled");
      ticking = false;
      return;
    }
    var y = window.scrollY || document.documentElement.scrollTop || 0;
    header.classList.toggle("app-header--scrolled", y > 8);
    var ae = document.activeElement;
    var typing =
      ae &&
      /^(INPUT|TEXTAREA|SELECT)$/i.test(ae.tagName) &&
      ae.type !== "checkbox" &&
      ae.type !== "radio";
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
