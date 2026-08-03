(function () {
  "use strict";

  function isMobileClass() {
    var c = document.documentElement.getAttribute("data-pbr-class") || "";
    var view = document.documentElement.getAttribute("data-pbr-view") || "";
    return c === "mobile" || view === "phone" || view === "tablet";
  }

  function applySidebarForView() {
    var hubs = document.querySelectorAll("[data-pbr-sidebar-hub]");
    if (!hubs.length) return;

    var view = document.documentElement.getAttribute("data-pbr-view") || "desktop";
    var deviceClass = document.documentElement.getAttribute("data-pbr-class") || "computer";
    var expandAll = view === "tv" || view === "large" || deviceClass === "tv";
    var mobile = isMobileClass();

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
          // En móvil se pueden tener varias secciones abiertas a la vez.
          if (currentClass === "mobile" || currentView === "phone" || currentView === "tablet") return;
          if (!details.open) return;
          accordions.forEach(function (other) {
            if (other !== details && other.open) {
              other.open = false;
            }
          });
        });
      });

      // En móvil: abrir TODAS las secciones para que se vean las opciones al scrollear.
      if (mobile) {
        accordions.forEach(function (details) {
          details.open = true;
        });
      } else {
        var active = hub.querySelector("a.is-active");
        if (active) {
          var parentAccord = active.closest("[data-pbr-accord]");
          if (parentAccord) parentAccord.open = true;
        }
      }
    });
  }

  function setupMobileDrawer() {
    var sidebar = document.getElementById("pbr-app-sidebar");
    if (!sidebar) return;

    var headerInner = document.querySelector(".app-header .app-header__inner");
    var backdrop = document.getElementById("pbr-nav-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "pbr-nav-backdrop";
      backdrop.className = "app-nav-backdrop";
      backdrop.hidden = true;
      document.body.appendChild(backdrop);
    }

    var toggle = document.getElementById("pbr-menu-toggle");
    if (!toggle && headerInner) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.id = "pbr-menu-toggle";
      toggle.className = "app-menu-toggle";
      toggle.setAttribute("aria-controls", "pbr-app-sidebar");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Abrir menú");
      toggle.innerHTML =
        '<svg class="app-menu-toggle__icon app-menu-toggle__icon--open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>' +
        '<svg class="app-menu-toggle__icon app-menu-toggle__icon--close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" hidden><path d="M18 6L6 18M6 6l12 12"/></svg>' +
        "<span>Menú</span>";
      headerInner.insertBefore(toggle, headerInner.firstChild);
    }

    function setOpen(open) {
      document.documentElement.classList.toggle("app-nav-open", open);
      document.body.classList.toggle("app-nav-open", open);
      if (toggle) {
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.setAttribute("aria-label", open ? "Cerrar menú" : "Abrir menú");
        var icOpen = toggle.querySelector(".app-menu-toggle__icon--open");
        var icClose = toggle.querySelector(".app-menu-toggle__icon--close");
        if (icOpen) icOpen.hidden = open;
        if (icClose) icClose.hidden = !open;
      }
      if (backdrop) backdrop.hidden = !open;
      if (sidebar) {
        sidebar.setAttribute("aria-hidden", open || !isMobileClass() ? "false" : "true");
      }
    }

    function closeNav() {
      setOpen(false);
    }

    if (toggle && !toggle.__pbrBound) {
      toggle.__pbrBound = true;
      toggle.addEventListener("click", function () {
        if (!isMobileClass()) return;
        setOpen(!document.body.classList.contains("app-nav-open"));
      });
    }

    if (backdrop && !backdrop.__pbrBound) {
      backdrop.__pbrBound = true;
      backdrop.addEventListener("click", closeNav);
    }

    if (sidebar && !sidebar.__pbrNavBound) {
      sidebar.__pbrNavBound = true;
      sidebar.addEventListener("click", function (e) {
        var a = e.target.closest("a");
        if (a && isMobileClass()) closeNav();
      });
    }

    if (!document.__pbrEscBound) {
      document.__pbrEscBound = true;
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") closeNav();
      });
    }

    if (!isMobileClass()) closeNav();
    else if (sidebar) {
      sidebar.setAttribute(
        "aria-hidden",
        document.body.classList.contains("app-nav-open") ? "false" : "true"
      );
    }
  }

  applySidebarForView();
  setupMobileDrawer();
  window.addEventListener("pbr:viewport", function () {
    applySidebarForView();
    setupMobileDrawer();
  });
})();
