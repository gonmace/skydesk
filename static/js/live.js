// Tiempo real (Django Channels). CSP-safe: sin inline. Se conecta a /ws/live/ y:
//  - 'board.changed'  -> refresca el tablero (window.refreshBoard, ver board-search.js),
//                        con debounce para coalescer ráfagas de eventos.
//  - 'ticket.changed' -> si es el ticket que se está viendo (ver #live-ticket-marker en
//                        ticket_detail.html), recarga la página (v1 simple).
//  - 'comment.new'    -> mensaje nuevo en el seguimiento del ticket visible: appendea
//                        por AJAX (window.chatFetchNew, ver chat-submit.js) SIN recargar,
//                        para no pisar lo que el usuario esté escribiendo.
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
  // El detalle hereda el seguimiento de su cadena de padres (derivar/dividir):
  // también hay que refrescar cuando cambia cualquiera de esos tickets.
  var watchedThreadIds = [];
  if (marker && marker.getAttribute('data-thread-ids')) {
    watchedThreadIds = marker.getAttribute('data-thread-ids').split(',').filter(Boolean);
  } else if (watchedTicketId) {
    watchedThreadIds = [watchedTicketId];
  }

  // Una acción propia (ej. "Dividir") puede mutar el ticket que se está viendo y disparar
  // su propio broadcast 'ticket.changed' — y lo hace ANTES de que el navegador reciba la
  // respuesta del form (el broadcast sale desde la mitad de la vista, el redirect es lo
  // último). Por eso `beforeunload` solo, que recién se dispara cuando llega esa respuesta,
  // no alcanza a marcar `navigating` a tiempo: el mensaje WS gana la carrera y el reload de
  // acá abajo compite con la navegación del form, a veces dejando al usuario de vuelta en
  // la misma página en lugar del destino real. El `submit` de acá abajo cierra la carrera
  // en el origen: se dispara sincrónicamente en el momento del envío real (antes de que el
  // form llegue siquiera a la red), y `!ev.defaultPrevented` evita el falso positivo del
  // primer `submit` de un form `data-confirm` (ese lo cancela app.js hasta que se confirma
  // el modal — ver static/js/app.js). `beforeunload` queda como red de contención extra
  // para navegación que no pasa por un submit (ej. click en un link).
  var navigating = false;
  window.addEventListener('beforeunload', function () { navigating = true; });
  document.addEventListener('submit', function (ev) {
    if (!ev.defaultPrevented) navigating = true;
  });

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
      if (!navigating && watchedThreadIds.indexOf(String(data.ticket_id)) !== -1) {
        window.location.reload();
      }
    } else if (data.type === 'comment.new') {
      // Appendear es inofensivo aunque haya una navegación en curso — sin chequear
      // `navigating` (chatFetchNew ya dedupea por data-comment-id).
      if (watchedThreadIds.indexOf(String(data.ticket_id)) !== -1 && window.chatFetchNew) {
        window.chatFetchNew();
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
      watchedThreadIds.forEach(function (id) {
        socket.send(JSON.stringify({ action: 'subscribe_ticket', id: parseInt(id, 10) }));
      });
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
