(function () {
  "use strict";

  var header = document.getElementById("pbr-app-header");
  if (!header) return;

  var lastScroll = 0;
  var ticking = false;

  function onScroll() {
    var y = window.scrollY || document.documentElement.scrollTop || 0;
    header.classList.toggle("app-header--scrolled", y > 8);
    header.classList.toggle("app-header--hide", y > lastScroll && y > 120);
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
