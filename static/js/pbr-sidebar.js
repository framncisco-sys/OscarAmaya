(function () {
  "use strict";

  var SEARCH_KEY = "pbr-sidebar-search-v1";

  function isMobileClass() {
    var c = document.documentElement.getAttribute("data-pbr-class") || "";
    var view = document.documentElement.getAttribute("data-pbr-view") || "";
    return c === "mobile" || view === "phone" || view === "tablet";
  }

  function prefersReducedMotion() {
    return (
      document.documentElement.getAttribute("data-pbr-reduced-motion") === "1" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function norm(s) {
    return String(s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();
  }

  function linkLabel(a) {
    var t = a.getAttribute("data-pbr-nav") || "";
    if (t) return t;
    t = (a.textContent || "").replace(/\s+/g, " ").trim();
    a.setAttribute("data-pbr-nav", t);
    return t;
  }

  function indexNavItems() {
    var root = document.getElementById("pbr-sidebar-modules");
    if (!root) return;
    root.querySelectorAll("a[href]").forEach(function (a) {
      linkLabel(a);
    });
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
          if (currentClass === "mobile" || currentView === "phone" || currentView === "tablet") return;
          if (!details.open) return;
          accordions.forEach(function (other) {
            if (other !== details && other.open) {
              other.open = false;
            }
          });
        });
      });

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

  function scrollActiveIntoView() {
    if (isMobileClass()) return;
    var scroll = document.getElementById("pbr-sidebar-modules");
    var active = scroll && scroll.querySelector("a.is-active");
    if (!scroll || !active) return;
    window.requestAnimationFrame(function () {
      var sTop = scroll.scrollTop;
      var sH = scroll.clientHeight;
      var aTop = active.offsetTop;
      var aH = active.offsetHeight;
      var parent = active.offsetParent;
      while (parent && parent !== scroll) {
        aTop += parent.offsetTop;
        parent = parent.offsetParent;
      }
      if (aTop < sTop + 40 || aTop + aH > sTop + sH - 40) {
        scroll.scrollTo({
          top: Math.max(0, aTop - sH / 2 + aH / 2),
          behavior: prefersReducedMotion() ? "auto" : "smooth",
        });
      }
    });
  }

  function setupSearch() {
    var toggle = document.getElementById("pbr-sidebar-search-toggle");
    var panel = document.getElementById("pbr-sidebar-search-panel");
    var input = document.getElementById("pbr-sidebar-search");
    var clearBtn = document.getElementById("pbr-sidebar-search-clear");
    var root = document.getElementById("pbr-sidebar-modules");
    if (!toggle || !panel || !input || !root) return;

    function setOpen(open) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      panel.hidden = !open;
      toggle.classList.toggle("is-open", open);
      if (open) {
        window.setTimeout(function () {
          input.focus();
        }, 60);
      } else if (!input.value.trim()) {
        input.value = "";
        filterNav("");
        if (clearBtn) clearBtn.hidden = true;
      }
    }

    function filterNav(q) {
      var needle = norm(q);
      var hubs = root.querySelectorAll("[data-pbr-sidebar-hub]");
      var anyVisible = false;

      hubs.forEach(function (hub) {
        var hubMatch = false;
        var accordions = hub.querySelectorAll("[data-pbr-accord]");
        var quickLinks = hub.querySelectorAll(".app-sidebar__quick");

        quickLinks.forEach(function (link) {
          var match = !needle || norm(linkLabel(link)).indexOf(needle) !== -1;
          link.hidden = !match;
          if (match) hubMatch = true;
        });

        accordions.forEach(function (details) {
          var labelEl = details.querySelector(".app-sidebar__accord-label");
          var summaryText = norm(labelEl ? labelEl.textContent : "");
          var sectionMatch = summaryText.indexOf(needle) !== -1;
          var links = details.querySelectorAll(
            ".app-sidebar__accord-panel a[href], .app-sidebar__nav-item"
          );
          var linkMatch = false;
          links.forEach(function (a) {
            var match = !needle || sectionMatch || norm(linkLabel(a)).indexOf(needle) !== -1;
            a.hidden = !match;
            if (match) linkMatch = true;
          });
          var show = !needle || sectionMatch || linkMatch;
          details.hidden = !show;
          if (needle && linkMatch && !sectionMatch) details.open = true;
          if (show) hubMatch = true;
        });

        hub.hidden = !hubMatch && !!needle;
        if (hubMatch || !needle) anyVisible = true;
      });

      root.classList.toggle("is-filtering", !!needle);
      root.classList.toggle("is-filter-empty", !!needle && !anyVisible);
      if (clearBtn) clearBtn.hidden = !needle;
    }

    toggle.addEventListener("click", function () {
      setOpen(panel.hidden);
    });

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        input.value = "";
        filterNav("");
        clearBtn.hidden = true;
        input.focus();
      });
    }

    input.addEventListener("input", function () {
      filterNav(input.value);
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        input.value = "";
        filterNav("");
        setOpen(false);
        toggle.focus();
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      var tag = (e.target && e.target.tagName) || "";
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.target.isContentEditable) return;
      e.preventDefault();
      setOpen(true);
    });

    try {
      var saved = sessionStorage.getItem(SEARCH_KEY);
      if (saved) {
        input.value = saved;
        filterNav(saved);
        setOpen(true);
      }
    } catch (err) {}

    input.addEventListener("change", function () {
      try {
        sessionStorage.setItem(SEARCH_KEY, input.value);
      } catch (err2) {}
    });
  }

  function setupNavRipple() {
    if (prefersReducedMotion()) return;
    var root = document.getElementById("pbr-sidebar-modules");
    if (!root) return;
    root.addEventListener("click", function (e) {
      var a = e.target.closest(".app-sidebar__accord-panel a, .app-sidebar__quick");
      if (!a || a.hidden) return;
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

  function init() {
    indexNavItems();
    applySidebarForView();
    setupSearch();
    setupNavRipple();
    setupMobileDrawer();
    scrollActiveIntoView();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.addEventListener("pbr:viewport", function () {
    applySidebarForView();
    setupMobileDrawer();
    scrollActiveIntoView();
  });
})();
