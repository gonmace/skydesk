// Al clickear el ícono "Dividido"/"Derivado" de una card (data-highlight-children), el
// ícono de tijera de una parte dividida (data-highlight-siblings) o el ícono de
// multiproducto (data-highlight-ticket), resalta un momento las cards relacionadas en
// vez de navegar (en cualquier columna del mismo tablero).
// CSP-safe: sin inline. Delegado en [data-kanban] (no en las cards) para sobrevivir el
// reemplazo del fragmento por AJAX (board-search.js hace board.innerHTML = html).
(function () {
  'use strict';

  var HIGHLIGHT_MS = 1200;
  var ATTRS = ['data-highlight-children', 'data-highlight-siblings', 'data-highlight-ticket'];

  function highlight(board, ids) {
    ids.forEach(function (id) {
      // querySelectorAll: un ticket multiproducto tiene VARIAS cards con el mismo
      // data-ticket-id (una por subticket de ejecutor) — se resaltan todas.
      var cards = board.querySelectorAll('.ticket-card[data-ticket-id="' + id + '"]');
      Array.prototype.forEach.call(cards, function (card) {
        card.classList.remove('card-highlight');
        // eslint-disable-next-line no-unused-expressions
        card.offsetWidth; // reinicia la animación si se clickea varias veces seguidas
        card.classList.add('card-highlight');
        setTimeout(function () { card.classList.remove('card-highlight'); }, HIGHLIGHT_MS);
      });
    });
  }

  function init() {
    var board = document.querySelector('[data-kanban]');
    if (!board || board.dataset.highlightBound) return;
    board.dataset.highlightBound = '1';

    board.addEventListener('click', function (e) {
      var trigger = e.target.closest(ATTRS.map(function (a) { return '[' + a + ']'; }).join(','));
      if (!trigger) return;
      var attr = ATTRS.filter(function (a) { return trigger.hasAttribute(a); })[0];
      var ids = (trigger.getAttribute(attr) || '').split(',').filter(Boolean);
      if (!ids.length) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return; // dejar abrir en pestaña nueva
      e.preventDefault();
      highlight(board, ids);
    });
  }

  window.initSubdivideHighlight = init;
  init();
})();
