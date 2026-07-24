/**
 * Login: validación, mostrar contraseña, brillo en panel y tiles de marca.
 */
(function () {
  "use strict";

  var form = document.getElementById("pbr-login-form");
  var stage = document.querySelector("[data-pbr-login-stage]");
  var panel = document.querySelector("[data-login-panel]");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (stage && !reduceMotion) {
    var tiles = stage.querySelectorAll("[data-login-brand]");
    tiles.forEach(function (tile) {
      tile.addEventListener("pointermove", function (e) {
        var rect = tile.getBoundingClientRect();
        tile.style.setProperty("--login-mx", ((e.clientX - rect.left) / rect.width) * 100 + "%");
        tile.style.setProperty("--login-my", ((e.clientY - rect.top) / rect.height) * 100 + "%");
      });
    });
    if (panel) {
      panel.addEventListener("pointermove", function (e) {
        var rect = panel.getBoundingClientRect();
        panel.style.setProperty("--login-mx", ((e.clientX - rect.left) / rect.width) * 100 + "%");
        panel.style.setProperty("--login-my", ((e.clientY - rect.top) / rect.height) * 100 + "%");
      });
    }
  }

  if (!form) return;

  var submitBtn = document.getElementById("pbr-login-submit");
  var usernameInput = form.querySelector('input[name="username"]');
  var passwordInput = form.querySelector('input[name="password"]');
  var toggleBtn = document.getElementById("pbr-login-toggle-pw");

  function fieldWrap(input) {
    return input ? input.closest(".login-field") : null;
  }

  function setFieldInvalid(input, message) {
    var wrap = fieldWrap(input);
    if (!wrap) return;
    wrap.classList.add("login-field--invalid");
    var errId = input.name === "username" ? "login-error-username" : "login-error-password";
    var err = document.getElementById(errId);
    if (!err) {
      err = document.createElement("p");
      err.className = "login-field__error";
      err.id = errId;
      wrap.appendChild(err);
    }
    err.textContent = message;
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", errId);
  }

  function clearFieldInvalid(input) {
    var wrap = fieldWrap(input);
    if (wrap) wrap.classList.remove("login-field--invalid");
    input.removeAttribute("aria-invalid");
    var errId = input.getAttribute("aria-describedby");
    if (errId) {
      var err = document.getElementById(errId);
      if (err && err.parentNode === wrap) err.remove();
      input.removeAttribute("aria-describedby");
    }
  }

  function validateClient() {
    var ok = true;
    if (usernameInput) {
      var user = usernameInput.value.trim();
      if (!user) {
        setFieldInvalid(usernameInput, "Ingrese su nombre de usuario.");
        ok = false;
      } else if (user.length < 2) {
        setFieldInvalid(usernameInput, "El usuario debe tener al menos 2 caracteres.");
        ok = false;
      } else {
        clearFieldInvalid(usernameInput);
      }
    }
    if (passwordInput) {
      if (!passwordInput.value) {
        setFieldInvalid(passwordInput, "Ingrese su contraseña.");
        ok = false;
      } else {
        clearFieldInvalid(passwordInput);
      }
    }
    return ok;
  }

  if (toggleBtn && passwordInput) {
    toggleBtn.addEventListener("click", function () {
      var show = passwordInput.type === "password";
      passwordInput.type = show ? "text" : "password";
      toggleBtn.setAttribute("aria-pressed", show ? "true" : "false");
      toggleBtn.setAttribute("aria-label", show ? "Ocultar contraseña" : "Mostrar contraseña");
      toggleBtn.title = show ? "Ocultar contraseña" : "Mostrar contraseña";
      var showIcon = toggleBtn.querySelector(".login-field__toggle-icon--show");
      var hideIcon = toggleBtn.querySelector(".login-field__toggle-icon--hide");
      if (showIcon) showIcon.hidden = show;
      if (hideIcon) hideIcon.hidden = !show;
    });
  }

  [usernameInput, passwordInput].forEach(function (input) {
    if (!input) return;
    input.addEventListener("input", function () {
      if (input.value.trim() || input.value) {
        clearFieldInvalid(input);
      }
    });
  });

  form.addEventListener("submit", function (ev) {
    if (!validateClient()) {
      ev.preventDefault();
      var firstInvalid = form.querySelector(".login-field--invalid input");
      if (firstInvalid) firstInvalid.focus();
      return;
    }
    if (usernameInput) {
      usernameInput.value = usernameInput.value.trim();
    }
    if (submitBtn) {
      submitBtn.classList.add("is-loading");
      submitBtn.disabled = true;
    }
  });

  if (usernameInput && !usernameInput.value) {
    usernameInput.focus();
  } else if (passwordInput && usernameInput && usernameInput.value) {
    passwordInput.focus();
  }
})();
