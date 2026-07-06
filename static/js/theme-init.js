// Aplica el tema guardado ANTES del primer paint: se carga bloqueante (sin defer)
// en el <head> de base.html. Es un archivo externo y no un <script> inline porque
// el CSP de producción no permite inline. El toggle que escribe la clave vive en
// app.js (data-theme-toggle).
(function () {
  'use strict';
  try {
    var theme = localStorage.getItem('skydesk-theme');
    if (theme) document.documentElement.setAttribute('data-theme', theme);
  } catch (e) {}
})();
