// Helpers globales de la app (CSP-safe: sin inline). Tema + confirmaciones.
(function () {
  'use strict';

  var THEME_KEY = 'skydesk-theme';

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
  }

  // Aplicar tema guardado al cargar.
  try {
    var saved = localStorage.getItem(THEME_KEY);
    if (saved) applyTheme(saved);
  } catch (e) {}

  document.addEventListener('click', function (ev) {
    var toggle = ev.target.closest('[data-theme-toggle]');
    if (toggle) {
      var current = document.documentElement.getAttribute('data-theme') || 'light';
      var next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    }
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
})();
