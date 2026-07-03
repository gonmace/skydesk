// Drag & drop del tablero kanban. Requiere sortable.min.js cargado antes.
// CSP-safe: sin inline; token CSRF de <meta name="csrf-token">.
// Dos modos: 'ticket' (coordinador, no arrastrable) y 'subticket' (ejecutor mueve su subticket).
// Expone window.initKanban() para re-inicializar tras recargar el fragmento por AJAX.
(function () {
  'use strict';

  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrftoken = meta ? meta.getAttribute('content') : '';
  var ALLOWED = { TODO: 1, IN_PROGRESS: 1, WAITING: 1, DONE: 1 };

  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrftoken,
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(body)
    });
  }

  function persistTicketOrder(board, column) {
    // .is-readonly = subtickets de un ticket con subproductos mostrados en el tablero
    // del coordinador (ver _subticket_cards en views.py): no tienen posición propia de
    // ticket, así que no deben entrar en el order que recibe ticket_move.
    var order = Array.prototype.map.call(
      column.querySelectorAll('.ticket-card:not(.is-readonly)'),
      function (el) { return parseInt(el.getAttribute('data-ticket-id'), 10); }
    );
    post(board.getAttribute('data-move-url'), {
      status: column.getAttribute('data-status'), order: order
    }).catch(function () { window.location.reload(); });
  }

  function persistAssignment(board, item, toColumn) {
    post(board.getAttribute('data-assignment-move-url'), {
      assignment: parseInt(item.getAttribute('data-assignment-id'), 10),
      status: toColumn.getAttribute('data-status')
    }).then(function (r) {
      if (!r.ok) { window.location.reload(); return; }
      // El servidor puede fusionar/separar cards multiproducto (mismo ticket, mismo
      // estado) — SortableJS solo movió el nodo que arrastramos, así que hace falta
      // refrescar el fragmento para que la fusión/separación (y el fantasma) se vean.
      if (window.refreshBoard) window.refreshBoard();
    }).catch(function () { window.location.reload(); });
  }

  function init() {
    var board = document.querySelector('[data-kanban]');
    if (!board || typeof Sortable === 'undefined') return;
    if (board.getAttribute('data-can-move') !== '1') return;
    var mode = board.getAttribute('data-mode') || 'ticket';

    Array.prototype.forEach.call(board.querySelectorAll('.kanban-col'), function (col) {
      var existing = Sortable.get(col);
      if (existing) existing.destroy();
      new Sortable(col, {
        group: 'kanban',
        draggable: '.ticket-card',
        // fantasmas, suspendidos y subtickets de solo lectura (tablero del coordinador
        // sobre tickets con subproductos) no se arrastran.
        filter: '.is-ghost, .is-locked, .is-readonly',
        animation: 150,
        ghostClass: 'opacity-40',
        delay: 150,
        delayOnTouchOnly: true,
        touchStartThreshold: 5,
        onMove: function (evt) {
          if (mode === 'subticket') {
            return !!ALLOWED[evt.to.getAttribute('data-status')];
          }
          return true;
        },
        onEnd: function (evt) {
          if (mode === 'subticket') {
            persistAssignment(board, evt.item, evt.to);
          } else {
            persistTicketOrder(board, evt.to);
            if (evt.from !== evt.to) persistTicketOrder(board, evt.from);
          }
        }
      });
    });
  }

  window.initKanban = init;
  init();
})();
