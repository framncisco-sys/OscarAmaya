(function () {
  "use strict";

  function applySidebarForView() {
    var hubs = document.querySelectorAll("[data-pbr-sidebar-hub]");
    if (!hubs.length) return;

    var view = document.documentElement.getAttribute("data-pbr-view") || "desktop";
    var deviceClass = document.documentElement.getAttribute("data-pbr-class") || "computer";
    var expandAll = view === "tv" || view === "large" || deviceClass === "tv";
    var isMobile = deviceClass === "mobile" || view === "phone" || view === "tablet";

    hubs.forEach(function (hub) {
      var accordions = hub.querySelectorAll("[data-pbr-accord]");

      if (expandAll) {
        accordions.forEach(function (details) {
          details.open = true;
        });
      }

      accordions.forEach(function (details) {
        if (details.__pbrAccordBound) return;
        details.__pbrAccordBound = true;
        details.addEventListener("toggle", function () {
          var currentView = document.documentElement.getAttribute("data-pbr-view") || "desktop";
          var currentClass = document.documentElement.getAttribute("data-pbr-class") || "computer";
          if (currentView === "tv" || currentView === "large" || currentClass === "tv") return;
          if (!details.open) return;
          accordions.forEach(function (other) {
            if (other !== details && other.open) {
              other.open = false;
            }
          });
        });
      });

      var active = hub.querySelector("a.is-active");
      if (active) {
        var parentAccord = active.closest("[data-pbr-accord]");
        if (parentAccord) {
          parentAccord.open = true;
        }
        if (isMobile) {
          window.requestAnimationFrame(function () {
            active.scrollIntoView({ block: "nearest", behavior: "smooth" });
          });
        }
      }
    });
  }

  applySidebarForView();
  window.addEventListener("pbr:viewport", applySidebarForView);
})();
