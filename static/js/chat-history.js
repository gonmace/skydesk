// "Cargar mensajes anteriores" / "Cargar más adjuntos" en el detalle de ticket: pagina
// el chat de seguimiento y su galería de adjuntos con fetch + prepend/append de
// fragmentos HTML (ver tickets:comment_history / tickets:chat_attachments_more).
// CSP-safe: sin inline.
(function () {
  'use strict';

  function setLoading(btn) {
    btn.disabled = true;
    btn.dataset.label = btn.textContent;
    btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span> Cargando…';
  }

  function restore(btn) {
    btn.disabled = false;
    btn.textContent = btn.dataset.label;
  }

  function fetchMore(btn) {
    var url = btn.getAttribute('data-url') + '?before=' + encodeURIComponent(btn.getAttribute('data-before'));
    return fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); });
  }

  document.addEventListener('click', function (ev) {
    var older = ev.target.closest('[data-load-older]');
    if (older) {
      ev.preventDefault();
      loadOlderComments(older);
      return;
    }
    var more = ev.target.closest('[data-load-more-attachments]');
    if (more) {
      ev.preventDefault();
      loadMoreAttachments(more);
    }
  });

  function loadOlderComments(btn) {
    var wrap = btn.closest('[data-load-older-wrap]');
    var container = document.querySelector('[data-chat-messages]');
    if (!wrap || !container) return;
    setLoading(btn);
    fetchMore(btn)
      .then(function (data) {
        if (!data.ok) throw new Error('bad response');
        // Insertar arriba corre visualmente el contenido hacia abajo — se compensa el
        // scroll con la diferencia de altura para que el usuario no pierda su lugar.
        var prevHeight = container.scrollHeight;
        wrap.insertAdjacentHTML('afterend', data.html);
        container.scrollTop += (container.scrollHeight - prevHeight);
        if (data.has_older) {
          btn.setAttribute('data-before', data.oldest);
          restore(btn);
        } else {
          wrap.remove();
        }
      })
      .catch(function () {
        restore(btn);
        if (window.Alert) Alert.show('No se pudieron cargar los mensajes anteriores.', 'error');
      });
  }

  function loadMoreAttachments(btn) {
    var wrap = btn.closest('[data-load-more-attachments-wrap]');
    var grid = document.querySelector('[data-gallery-grid]');
    if (!wrap || !grid) return;
    setLoading(btn);
    fetchMore(btn)
      .then(function (data) {
        if (!data.ok) throw new Error('bad response');
        grid.insertAdjacentHTML('beforeend', data.html);
        if (data.has_more) {
          btn.setAttribute('data-before', data.oldest);
          restore(btn);
        } else {
          wrap.remove();
        }
      })
      .catch(function () {
        restore(btn);
        if (window.Alert) Alert.show('No se pudieron cargar más adjuntos.', 'error');
      });
  }
})();
