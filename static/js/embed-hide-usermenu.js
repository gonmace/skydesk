// Cuando SkyDesk corre embebido en el iframe de Nextcloud (External Sites): oculta el
// avatar y deshabilita el dropdown (perfil, "Cerrar sesión", etc. — la sesión se gestiona
// desde Nextcloud), pero deja visible el badge de rol junto al botón del menú.
(function () {
  if (window.self === window.top) return; // standalone: no tocar nada

  var avatar = document.getElementById('nc-avatar');
  if (avatar) avatar.style.display = 'none';

  var dropdownContent = document.getElementById('nc-user-dropdown-content');
  if (dropdownContent) dropdownContent.style.display = 'none';
})();
