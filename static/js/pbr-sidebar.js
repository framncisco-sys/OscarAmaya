(function () {
  "use strict";

  var ACCORD_STORAGE_KEY = "pbr-sidebar-accord-open";

  function isMobileClass() {
    var c = document.documentElement.getAttribute("data-pbr-class") || "";
    var view = document.documentElement.getAttribute("data-pbr-view") || "";
    return c === "mobile" || view === "phone" || view === "tablet";
  }

  function normalizeSearchText(value) {
    return (value || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();
  }

  function accordId(details) {
    var hub = details.closest("[data-pbr-sidebar-hub]");
    var hubLabel = hub ? hub.getAttribute("aria-label") || "hub" : "hub";
    var label = details.querySelector(".app-sidebar__accord-label");
    var text = label ? label.textContent.trim() : "section";
    return hubLabel + "::" + text;
  }

  function readAccordState() {
    try {
      var raw = sessionStorage.getItem(ACCORD_STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function writeAccordState(state) {
    try {
      sessionStorage.setItem(ACCORD_STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      /* ignore */
    }
  }

  function setupSearchToggle() {
    var toggle = document.getElementById("pbr-sidebar-search-toggle");
    var panel = document.getElementById("pbr-sidebar-search-panel");
    var input = document.getElementById("pbr-sidebar-search");
    if (!toggle || !panel) return;

    function setOpen(open) {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open && input) {
        window.setTimeout(function () {
          input.focus();
        }, 60);
      }
    }

    toggle.addEventListener("click", function () {
      setOpen(panel.hidden);
    });

    return setOpen;
  }

  function setupSidebarSearch(setSearchOpen) {
    var input = document.getElementById("pbr-sidebar-search");
    var clearBtn = document.getElementById("pbr-sidebar-search-clear");
    var modules = document.getElementById("pbr-sidebar-modules");
    var emptyMsg = document.getElementById("pbr-sidebar-search-empty");
    if (!input || !modules) return;

    function setHidden(el, hidden) {
      if (!el) return;
      el.hidden = hidden;
      el.classList.toggle("is-search-hidden", hidden);
    }

    function resetVisibility() {
      modules.querySelectorAll(".is-search-hidden").forEach(function (el) {
        el.hidden = false;
        el.classList.remove("is-search-hidden");
      });
      modules.querySelectorAll("[data-pbr-sidebar-hub]").forEach(function (hub) {
        hub.hidden = false;
      });
      if (emptyMsg) emptyMsg.hidden = true;
      if (clearBtn) clearBtn.hidden = true;
    }

    function applyFilter() {
      var q = normalizeSearchText(input.value);
      if (clearBtn) clearBtn.hidden = !q;
      if (!q) {
        resetVisibility();
        applySidebarForView();
        return;
      }

      var anyVisible = false;
      modules.querySelectorAll("[data-pbr-sidebar-hub]").forEach(function (hub) {
        var hubVisible = false;

        hub.querySelectorAll(".app-sidebar__quick").forEach(function (link) {
          var match = normalizeSearchText(link.textContent).indexOf(q) >= 0;
          setHidden(link, !match);
          if (match) hubVisible = true;
        });

        hub.querySelectorAll("[data-pbr-accord]").forEach(function (details) {
          var accordVisible = false;
          var summary = details.querySelector(".app-sidebar__accord-summary");
          var summaryMatch =
            summary && normalizeSearchText(summary.textContent).indexOf(q) >= 0;

          details.querySelectorAll(".app-sidebar__accord-panel a").forEach(function (a) {
            var match = summaryMatch || normalizeSearchText(a.textContent).indexOf(q) >= 0;
            setHidden(a, !match);
            if (match) accordVisible = true;
          });

          if (accordVisible) {
            details.open = true;
            details.classList.add("is-search-open");
          } else {
            details.classList.remove("is-search-open");
          }
          setHidden(details, !accordVisible);
          if (accordVisible) hubVisible = true;
        });

        hub.hidden = !hubVisible;
        if (hubVisible) anyVisible = true;
      });

      if (emptyMsg) emptyMsg.hidden = anyVisible;
    }

    input.addEventListener("input", applyFilter);
    input.addEventListener("search", applyFilter);

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        input.value = "";
        input.focus();
        resetVisibility();
        applySidebarForView();
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      var tag = (e.target && e.target.tagName) || "";
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
      if (!document.getElementById("pbr-app-sidebar")) return;
      e.preventDefault();
      if (setSearchOpen) setSearchOpen(true);
      input.focus();
      input.select();
    });
  }

  function applySidebarForView() {
    var hubs = document.querySelectorAll("[data-pbr-sidebar-hub]");
    if (!hubs.length) return;

    var searchInput = document.getElementById("pbr-sidebar-search");
    if (searchInput && normalizeSearchText(searchInput.value)) return;

    var view = document.documentElement.getAttribute("data-pbr-view") || "desktop";
    var deviceClass = document.documentElement.getAttribute("data-pbr-class") || "computer";
    var expandAll = view === "tv" || view === "large" || deviceClass === "tv";
    var mobile = isMobileClass();
    var saved = readAccordState();
    var hasActive = !!document.querySelector("#pbr-sidebar-modules a.is-active");

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
          var id = accordId(details);
          var state = readAccordState();
          state[id] = details.open;
          writeAccordState(state);

          var currentView = document.documentElement.getAttribute("data-pbr-view") || "desktop";
          var currentClass = document.documentElement.getAttribute("data-pbr-class") || "computer";
          if (currentView === "tv" || currentView === "large" || currentClass === "tv") return;
          if (currentClass === "mobile" || currentView === "phone" || currentView === "tablet") return;
          if (!details.open) return;
          accordions.forEach(function (other) {
            if (other !== details && other.open) {
              other.open = false;
              var oid = accordId(other);
              var st = readAccordState();
              st[oid] = false;
              writeAccordState(st);
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
        } else if (!hasActive) {
          accordions.forEach(function (details) {
            var id = accordId(details);
            if (Object.prototype.hasOwnProperty.call(saved, id)) {
              details.open = !!saved[id];
            }
          });
        }
      }
    });
  }

  function scrollActiveIntoView() {
    var modules = document.getElementById("pbr-sidebar-modules");
    if (!modules) return;
    var active = modules.querySelector("a.is-active");
    if (!active) return;
    window.requestAnimationFrame(function () {
      try {
        active.scrollIntoView({ block: "nearest", behavior: "smooth" });
      } catch (e) {
        active.scrollIntoView(true);
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

  var setSearchOpen = setupSearchToggle();
  setupSidebarSearch(setSearchOpen);
  applySidebarForView();
  scrollActiveIntoView();
  setupMobileDrawer();
  window.addEventListener("pbr:viewport", function () {
    applySidebarForView();
    setupMobileDrawer();
  });
})();
