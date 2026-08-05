/**
 * Modo sin conexión PBR:
 * - Aviso: consulta de pantallas cacheadas; guardar requiere internet.
 * - Cola IndexedDB solo si el formulario tiene data-pbr-offline="queue".
 * - Por defecto no encola pagos, validaciones ni formatos de venta.
 */
(function (global) {
  "use strict";

  var DB_NAME = "pbr-offline";
  var DB_VERSION = 1;
  var STORE = "outbox";
  var bar = document.getElementById("pbr-offline-bar");
  var toastHost = null;
  var syncing = false;

  function openDb() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
        }
      };
      req.onsuccess = function () {
        resolve(req.result);
      };
      req.onerror = function () {
        reject(req.error);
      };
    });
  }

  function withStore(mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, mode);
        var store = tx.objectStore(STORE);
        var result = fn(store);
        tx.oncomplete = function () {
          resolve(result);
        };
        tx.onerror = function () {
          reject(tx.error);
        };
      });
    });
  }

  function addOutboxItem(item) {
    return withStore("readwrite", function (store) {
      store.add(item);
    });
  }

  function getAllOutbox() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readonly");
        var req = tx.objectStore(STORE).getAll();
        req.onsuccess = function () {
          resolve(req.result || []);
        };
        req.onerror = function () {
          reject(req.error);
        };
      });
    });
  }

  function deleteOutboxItem(id) {
    return withStore("readwrite", function (store) {
      store.delete(id);
    });
  }

  function countOutbox() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readonly");
        var req = tx.objectStore(STORE).count();
        req.onsuccess = function () {
          resolve(req.result || 0);
        };
        req.onerror = function () {
          reject(req.error);
        };
      });
    });
  }

  function ensureToastHost() {
    if (toastHost) return toastHost;
    toastHost = document.createElement("div");
    toastHost.id = "pbr-offline-toast-host";
    toastHost.className = "pbr-offline-toast-host";
    toastHost.setAttribute("aria-live", "polite");
    document.body.appendChild(toastHost);
    return toastHost;
  }

  function showToast(message, kind) {
    var host = ensureToastHost();
    var el = document.createElement("div");
    el.className = "pbr-offline-toast pbr-offline-toast--" + (kind || "info");
    el.textContent = message;
    host.appendChild(el);
    window.setTimeout(function () {
      el.classList.add("is-leaving");
      window.setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 280);
    }, 4200);
  }

  function setBarState(state, pendingCount) {
    if (!bar) return;
    bar.classList.remove(
      "pbr-offline-bar--offline",
      "pbr-offline-bar--syncing",
      "pbr-offline-bar--ok"
    );
    document.body.classList.remove(
      "pbr-network-offline",
      "pbr-network-syncing",
      "pbr-network-ok-flash"
    );

    if (state === "offline") {
      bar.hidden = false;
      bar.classList.add("pbr-offline-bar--offline");
      document.body.classList.add("pbr-network-offline");
      bar.innerHTML =
        "<strong>Sin conexión.</strong> " +
        "Puede consultar pantallas ya abiertas. Para guardar o validar necesita internet." +
        (pendingCount
          ? " <span class='pbr-offline-bar__count'>Cola (solo pantallas permitidas): " +
            pendingCount +
            "</span>"
          : "");
      bar.setAttribute("aria-hidden", "false");
      return;
    }

    if (state === "syncing") {
      bar.hidden = false;
      bar.classList.add("pbr-offline-bar--syncing");
      document.body.classList.add("pbr-network-syncing");
      bar.innerHTML =
        "<strong>Conexión recuperada.</strong> Subiendo cambios pendientes" +
        (pendingCount ? " (" + pendingCount + ")" : "") +
        "…";
      bar.setAttribute("aria-hidden", "false");
      return;
    }

    if (state === "ok") {
      bar.hidden = false;
      bar.classList.add("pbr-offline-bar--ok");
      document.body.classList.add("pbr-network-ok-flash");
      bar.innerHTML =
        "<strong>En línea.</strong> Los cambios pendientes se enviaron al servidor.";
      bar.setAttribute("aria-hidden", "false");
      window.setTimeout(function () {
        if (navigator.onLine && !syncing) {
          bar.hidden = true;
          bar.setAttribute("aria-hidden", "true");
          document.body.classList.remove("pbr-network-ok-flash");
        }
      }, 3500);
      return;
    }

    bar.hidden = true;
    bar.setAttribute("aria-hidden", "true");
  }

  function refreshOfflineBar() {
    if (!navigator.onLine) {
      countOutbox()
        .then(function (n) {
          setBarState("offline", n);
        })
        .catch(function () {
          setBarState("offline", 0);
        });
      return;
    }
    if (!syncing) {
      bar.hidden = true;
      bar.setAttribute("aria-hidden", "true");
      document.body.classList.remove("pbr-network-offline", "pbr-network-syncing");
    }
  }

  function formToPayload(form) {
    var fd = new FormData(form);
    var entries = [];
    var fileNames = [];
    fd.forEach(function (value, key) {
      if (value instanceof File) {
        if (value.size > 0) {
          fileNames.push(value.name || key);
        }
        return;
      }
      entries.push({ key: key, type: "text", value: String(value) });
    });
    return {
      action: form.getAttribute("action") || window.location.href,
      method: (form.getAttribute("method") || "POST").toUpperCase(),
      entries: entries,
      fileNames: fileNames,
      page: window.location.pathname + window.location.search,
      createdAt: Date.now(),
      title: document.title || "Formulario",
    };
  }

  function getCookie(name) {
    var match = document.cookie.match(
      new RegExp("(?:^|; )" + name.replace(/([.$?*|{}()[\]\\/+^])/g, "\\$1") + "=([^;]*)")
    );
    return match ? decodeURIComponent(match[1]) : "";
  }

  function refreshCsrfInFormData(fd) {
    var token = getCookie("csrftoken");
    if (!token) return;
    if (typeof fd.set === "function") {
      fd.set("csrfmiddlewaretoken", token);
    } else {
      fd.append("csrfmiddlewaretoken", token);
    }
  }

  function isAuthForm(form) {
    var action = (form.getAttribute("action") || window.location.pathname || "").toLowerCase();
    if (action.indexOf("/login") !== -1 || action.indexOf("/logout") !== -1) return true;
    if (action.indexOf("reauth") !== -1 || action.indexOf("sensitive") !== -1) return true;
    if (form.id === "pbr-login-form") return true;
    return false;
  }

  function payloadToFormData(payload) {
    var fd = new FormData();
    (payload.entries || []).forEach(function (e) {
      fd.append(e.key, e.value);
    });
    refreshCsrfInFormData(fd);
    return { fd: fd, skippedFiles: payload.fileNames || [] };
  }

  function queueForm(form) {
    var payload = formToPayload(form);
    var hasFiles = payload.fileNames && payload.fileNames.length > 0;
    return addOutboxItem(payload).then(function () {
      showToast(
        hasFiles
          ? "Datos guardados en cola (sin Internet). Los archivos adjuntos deberá subirlos cuando haya red."
          : "Guardado en cola. Se enviará al servidor cuando haya Internet.",
        "warn"
      );
      return countOutbox().then(function (n) {
        setBarState("offline", n);
      });
    });
  }

  function syncOutbox() {
    if (!navigator.onLine || syncing) {
      return Promise.resolve({ ok: 0, fail: 0 });
    }
    syncing = true;
    return getAllOutbox()
      .then(function (items) {
        if (!items.length) {
          syncing = false;
          return { ok: 0, fail: 0 };
        }
        setBarState("syncing", items.length);
        var ok = 0;
        var fail = 0;
        var chain = Promise.resolve();
        items.forEach(function (item) {
          chain = chain.then(function () {
            var built = payloadToFormData(item);
            return fetch(item.action, {
              method: item.method || "POST",
              body: built.fd,
              credentials: "same-origin",
              headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-PBR-Offline-Sync": "1",
              },
            })
              .then(function (res) {
                if (res.ok || (res.status >= 300 && res.status < 400)) {
                  ok += 1;
                  return deleteOutboxItem(item.id);
                }
                /* 403 CSRF u otros: dejar en cola */
                fail += 1;
                return null;
              })
              .catch(function () {
                fail += 1;
              });
          });
        });
        return chain.then(function () {
          return { ok: ok, fail: fail };
        });
      })
      .then(function (stats) {
        syncing = false;
        if (stats.ok > 0 && stats.fail === 0) {
          setBarState("ok");
          showToast(
            stats.ok === 1
              ? "Se envió 1 cambio pendiente al servidor."
              : "Se enviaron " + stats.ok + " cambios pendientes al servidor.",
            "ok"
          );
        } else if (stats.ok > 0 && stats.fail > 0) {
          setBarState("ok");
          showToast(
            "Se enviaron " + stats.ok + " cambios. Quedaron " + stats.fail + " por reintentar.",
            "warn"
          );
        } else if (stats.fail > 0) {
          refreshOfflineBar();
          showToast("No se pudieron enviar algunos cambios. Se reintentará luego.", "warn");
        } else {
          refreshOfflineBar();
        }
        return stats;
      })
      .catch(function () {
        syncing = false;
        refreshOfflineBar();
        return { ok: 0, fail: 0 };
      });
  }

  function onOffline() {
    countOutbox()
      .then(function (n) {
        setBarState("offline", n);
        showToast(
          "Sin Internet. Puede consultar pantallas ya abiertas; para guardar necesita conexión.",
          "warn"
        );
      })
      .catch(function () {
        setBarState("offline", 0);
      });
  }

  function onOnline() {
    countOutbox()
      .then(function (n) {
        if (n > 0) {
          showToast("Internet recuperado. Sincronizando…", "info");
        } else {
          showToast("Internet recuperado.", "info");
        }
        return syncOutbox();
      })
      .then(function () {
        if (navigator.serviceWorker) {
          navigator.serviceWorker.getRegistration().then(function (reg) {
            if (reg) reg.update();
          });
        }
      })
      .catch(function () {
        syncOutbox();
      });
  }

  document.addEventListener(
    "submit",
    function (ev) {
      var form = ev.target;
      if (!form || form.tagName !== "FORM") return;
      if (form.getAttribute("data-pbr-offline") === "skip") return;
      if (isAuthForm(form)) return;

      // Con red: renovar CSRF del cookie (evita 403 por token en caché / cola vieja).
      if (navigator.onLine) {
        var token = getCookie("csrftoken");
        if (token) {
          var input = form.querySelector('input[name="csrfmiddlewaretoken"]');
          if (input) input.value = token;
        }
        return;
      }

      var method = (form.getAttribute("method") || "GET").toUpperCase();
      if (method === "GET") return;

      // Sin red: solo encolar si el formulario opta explícitamente (data-pbr-offline="queue").
      // Por defecto NO se guardan pagos, validaciones ni formatos en cola fantasma.
      ev.preventDefault();
      ev.stopPropagation();
      if (form.getAttribute("data-pbr-offline") === "queue") {
        queueForm(form).catch(function () {
          showToast("No se pudo guardar en cola. Intente de nuevo al tener Internet.", "warn");
        });
        return;
      }
      showToast(
        "Sin internet. Para guardar necesita conexión. Puede consultar pantallas ya abiertas.",
        "warn"
      );
    },
    true
  );

  window.addEventListener("offline", onOffline);
  window.addEventListener("online", onOnline);

  if (!navigator.onLine) {
    onOffline();
  } else {
    /* Por si quedó cola de una sesión anterior */
    countOutbox().then(function (n) {
      if (n > 0) syncOutbox();
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && navigator.onLine) {
      syncOutbox();
    }
  });

  global.pbrOffline = {
    sync: syncOutbox,
    pendingCount: countOutbox,
    refreshBar: refreshOfflineBar,
  };
})(window);
