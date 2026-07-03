// Tiempo real (Django Channels). CSP-safe: sin inline. Se conecta a /ws/live/ y:
//  - 'board.changed'  -> refresca el tablero (window.refreshBoard, ver board-search.js),
//                        con debounce para coalescer ráfagas de eventos.
//  - 'ticket.changed' -> si es el ticket que se está viendo (ver #live-ticket-marker en
//                        ticket_detail.html), recarga la página (v1 simple).
//  - 'notif.new'      -> re-pide el fragmento del badge/dropdown de notificaciones.
// Degrada en silencio si el WS no conecta (CSP, nginx sin /ws/, etc.): la app sigue
// funcionando normal, solo se pierde el push.
(function () {
  'use strict';

  var socket = null;
  var reconnectDelay = 1000;
  var MAX_RECONNECT_DELAY = 30000;
  var boardRefreshTimer = null;

  var marker = document.getElementById('live-ticket-marker');
  var watchedTicketId = marker ? marker.getAttribute('data-ticket-id') : null;

  function refreshBoardDebounced() {
    if (!window.refreshBoard) return;
    clearTimeout(boardRefreshTimer);
    boardRefreshTimer = setTimeout(window.refreshBoard, 400);
  }

  function refreshNotifMenu() {
    var host = document.getElementById('notif-menu');
    var url = host && host.getAttribute('data-notif-menu-url');
    if (!url) return;
    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.text(); })
      .then(function (html) { host.innerHTML = html; })
      .catch(function () {});
  }

  function handleMessage(event) {
    var data;
    try { data = JSON.parse(event.data); } catch (e) { return; }
    if (data.type === 'board.changed') {
      refreshBoardDebounced();
    } else if (data.type === 'ticket.changed') {
      if (watchedTicketId && String(data.ticket_id) === watchedTicketId) {
        window.location.reload();
      }
    } else if (data.type === 'notif.new') {
      refreshNotifMenu();
    }
  }

  function connect() {
    var proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    socket = new WebSocket(proto + '://' + window.location.host + '/ws/live/');

    socket.onopen = function () {
      reconnectDelay = 1000;
      if (watchedTicketId) {
        socket.send(JSON.stringify({ action: 'subscribe_ticket', id: parseInt(watchedTicketId, 10) }));
      }
    };
    socket.onmessage = handleMessage;
    socket.onclose = function () {
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    };
    socket.onerror = function () {
      // silencioso: onclose se dispara después y maneja el reintento.
    };
  }

  connect();
})();
