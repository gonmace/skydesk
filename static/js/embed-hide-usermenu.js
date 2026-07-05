// Cuando SkyDesk corre embebido en el iframe de Nextcloud (External Sites), oculta el
// menú de usuario (avatar, "Cerrar sesión") del header: dentro de Nextcloud la sesión se
// gestiona desde ahí, no tiene sentido ofrecer un logout aparte de SkyDesk.
(function () {
  if (window.self === window.top) return; // standalone: no tocar nada

  var menu = document.getElementById('nc-user-menu');
  if (menu) menu.style.display = 'none';
})();
