// Helpers globales de la app (CSP-safe: sin inline). Tema + confirmaciones.
(function () {
  'use strict';

  var THEME_KEY = 'skydesk-theme';

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
  }

  // El tema guardado se aplica en theme-init.js (bloqueante en el <head> de
  // base.html, antes del primer paint) — acá solo vive el toggle que lo escribe.

  document.addEventListener('click', function (ev) {
    var toggle = ev.target.closest('[data-theme-toggle]');
    if (toggle) {
      var current = document.documentElement.getAttribute('data-theme') || 'light';
      var next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    }
  });

  // Última pestaña del nav (Tablero, Mis tickets, Dashboard, …): se guarda al
  // visitarla y, al ENTRAR a la app cayendo en la raíz (primera carga de esta
  // pestaña del navegador — sessionStorage), se redirige a la guardada. Los clicks
  // posteriores en «Tablero» ya no redirigen porque la sesión deja de ser "fresca".
  // Solo cuentan paths presentes en el nav actual: si el rol perdió una sección,
  // la clave guardada se ignora en vez de redirigir a un 403.
  var TAB_KEY = 'skydesk-last-tab';
  var tabs = Array.prototype.map.call(
    document.querySelectorAll('[data-nav-tab]'),
    function (a) { return a.getAttribute('href'); }
  );
  if (tabs.length) {
    var path = window.location.pathname;
    try {
      var fresh = !sessionStorage.getItem('skydesk-visited');
      sessionStorage.setItem('skydesk-visited', '1');
      var lastTab = localStorage.getItem(TAB_KEY);
      if (fresh && path === '/' && lastTab && lastTab !== path && tabs.indexOf(lastTab) !== -1) {
        window.location.replace(lastTab);
      } else if (tabs.indexOf(path) !== -1) {
        localStorage.setItem(TAB_KEY, path);
      }
    } catch (e) {}
  }

  // Checkboxes con data-auto-submit (ej. toggles de estado): al cambiar, envían su form.
  // data-label-on/off (opcional): texto del title según el nuevo estado.
  function syncToggleLabel(el) {
    if (el.dataset.labelOn && el.dataset.labelOff) {
      el.title = el.checked ? el.dataset.labelOn : el.dataset.labelOff;
    }
  }

  document.addEventListener('change', function (ev) {
    var el = ev.target;
    if (!el.matches('[data-auto-submit]')) return;
    syncToggleLabel(el);
    var form = el.closest('form');
    if (form) { if (form.requestSubmit) form.requestSubmit(); else form.submit(); }
  });

  // Formularios con data-confirm: modal propio en vez del confirm() nativo del navegador.
  var confirmModal, confirmMsg, confirmOkBtn, pendingForm;

  function ensureConfirmModal() {
    if (confirmModal !== undefined) return confirmModal;
    confirmModal = document.getElementById('confirm-modal');
    if (!confirmModal) return null;
    confirmMsg = document.getElementById('confirm-modal-message');
    confirmOkBtn = document.getElementById('confirm-modal-ok');
    confirmOkBtn.addEventListener('click', function () {
      confirmModal.close();
      var form = pendingForm;
      pendingForm = null;
      if (form) {
        form.removeAttribute('data-confirm');
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
      }
    });
    return confirmModal;
  }

  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!form.matches('[data-confirm]')) return;
    var modal = ensureConfirmModal();
    if (!modal) return; // sin modal en el DOM: no bloquear el envío
    ev.preventDefault();
    confirmMsg.textContent = form.getAttribute('data-confirm');
    pendingForm = form;
    modal.showModal();
  });

  // Formularios con data-ajax: se envían por fetch (sin recargar la página) y el
  // resultado se muestra como toast usando el mismo mensaje que devolvería Django.
  function revertToggle(form) {
    var el = form.querySelector('[data-auto-submit]');
    if (!el) return;
    el.checked = !el.checked;
    syncToggleLabel(el);
  }

  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!form.matches('[data-ajax]')) return;
    ev.preventDefault();
    var btn = form.querySelector('button, [data-auto-submit]');
    if (btn) btn.disabled = true;
    fetch(form.getAttribute('action') || window.location.href, {
      method: 'POST',
      body: new FormData(form),
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.tag === 'error') revertToggle(form);
        if (!window.Alert || !data.message) return;
        var type = data.tag === 'debug' ? 'info' : (data.tag || 'info');
        Alert.show(data.message, type, { autoHide: 5000 });
      })
      .catch(function () {
        revertToggle(form);
        if (window.Alert) Alert.error('No se pudo completar la acción.');
      })
      .finally(function () { if (btn) btn.disabled = false; });
  });

  // Formularios con data-submit-spinner (ej. crear/editar ticket, que al asignar
  // dispara correos): al enviar, el botón submit muestra un spinner y se deshabilita
  // — sin feedback el POST parece colgado, y de paso se evita el doble submit.
  // Registrado DESPUÉS de data-confirm/data-ajax: si otro handler ya hizo
  // preventDefault, acá no se toca el botón.
  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!form.matches('[data-submit-spinner]') || ev.defaultPrevented) return;
    var btn = form.querySelector('button[type="submit"], button:not([type])');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span> ' +
      (btn.dataset.spinnerLabel || 'Guardando…');
  });
})();
