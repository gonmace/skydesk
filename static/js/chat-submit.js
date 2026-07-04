// Envía el form de seguimiento al presionar Enter (Shift+Enter = salto de línea).
// Cancela la edición inline al presionar el botón o Escape.
// CSP-safe: sin inline.
(function () {
  'use strict';

  // El área de mensajes tiene altura máxima: arrancar con el scroll abajo
  // para que se vean los mensajes más recientes. Se repite en window.load
  // porque las imágenes adjuntas cargan después y empujan el contenido.
  var messages = document.querySelector('[data-chat-messages]');
  function scrollToBottom() {
    if (messages) messages.scrollTop = messages.scrollHeight;
  }
  scrollToBottom();
  window.addEventListener('load', scrollToBottom);

  // Tras enviar un mensaje (POST + recarga completa), volver a enfocar el textarea
  // de compose para seguir escribiendo sin tener que hacer click de nuevo.
  // Ver #chat-compose en tickets/views.py::comment_add.
  if (window.location.hash === '#chat-compose') {
    var compose = document.getElementById('chat-compose');
    if (compose) {
      compose.focus();
      var len = compose.value.length;
      compose.setSelectionRange(len, len);
    }
    // Limpiar el hash para que un refresh no vuelva a robar el foco.
    history.replaceState(null, '', window.location.pathname + window.location.search);
  }

  // Enter envía el form contenedor (textarea del chat nuevo).
  Array.prototype.forEach.call(document.querySelectorAll('form[data-chat-submit] textarea'), function (ta) {
    ta.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
      e.preventDefault();
      ta.form.requestSubmit();
    });
  });

  // Al enviar con adjuntos cargados: mostrar spinner + "Subiendo adjuntos…" y
  // deshabilitar el botón para evitar doble envío (subir a Nextcloud puede tardar).
  // Es un submit normal (sin preventDefault) — el navegador sigue con la recarga.
  Array.prototype.forEach.call(document.querySelectorAll('form[data-chat-submit]'), function (form) {
    form.addEventListener('submit', function () {
      var hasFiles = false;
      Array.prototype.forEach.call(form.querySelectorAll('[data-dropzone-input]:not(:disabled)'), function (input) {
        if (input.files && input.files.length > 0) hasFiles = true;
      });
      if (!hasFiles) return;
      var indicator = form.querySelector('[data-chat-uploading]');
      if (indicator) { indicator.classList.remove('hidden'); indicator.classList.add('flex'); }
      var btn = form.querySelector('button[type=submit]');
      if (btn) btn.disabled = true;
    });
  });

  // Enter envía el form de edición inline; Escape cancela.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      var input = e.target.closest('[data-chat-edit-input]');
      if (input) {
        e.preventDefault();
        input.form.requestSubmit();
      }
    }
    if (e.key === 'Escape') {
      var details = e.target.closest('details[data-chat-edit]');
      if (details) details.open = false;
    }
  });

  // Botón cancelar cierra el <details>.
  document.addEventListener('click', function (e) {
    var cancel = e.target.closest('[data-chat-edit-cancel]');
    if (!cancel) return;
    var details = cancel.closest('details[data-chat-edit]');
    if (details) details.open = false;
  });
})();