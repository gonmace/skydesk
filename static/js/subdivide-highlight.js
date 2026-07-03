// Al clickear el ícono "Dividido" de una card, resalta un momento las cards de sus
// tickets derivados (en cualquier columna del mismo tablero). CSP-safe: sin inline.
// Delegado en [data-kanban] (no en las cards) para sobrevivir el reemplazo del
// fragmento por AJAX (board-search.js hace board.innerHTML = html).
(function () {
  'use strict';

  var HIGHLIGHT_MS = 1200;

  function init() {
    var board = document.querySelector('[data-kanban]');
    if (!board || board.dataset.highlightBound) return;
    board.dataset.highlightBound = '1';

    board.addEventListener('click', function (e) {
      var trigger = e.target.closest('[data-highlight-children]');
      if (!trigger) return;
      var raw = trigger.getAttribute('data-highlight-children') || '';
      var ids = raw.split(',').filter(Boolean);
      if (!ids.length) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return; // dejar abrir en pestaña nueva
      e.preventDefault();
      ids.forEach(function (id) {
        var card = board.querySelector('.ticket-card[data-ticket-id="' + id + '"]');
        if (!card) return;
        card.classList.remove('card-highlight');
        // eslint-disable-next-line no-unused-expressions
        card.offsetWidth; // reinicia la animación si se clickea varias veces seguidas
        card.classList.add('card-highlight');
        setTimeout(function () { card.classList.remove('card-highlight'); }, HIGHLIGHT_MS);
      });
    });
  }

  window.initSubdivideHighlight = init;
  init();
})();
