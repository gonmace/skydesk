// Cuando SkyDesk corre embebido en el iframe de Nextcloud (External Sites): oculta el
// logo y deshabilita el dropdown (perfil, "Cerrar sesión", etc. — la sesión se gestiona
// desde Nextcloud), pero deja visibles el avatar y el badge de rol.
(function () {
  if (window.self === window.top) return; // standalone: no tocar nada

  var logo = document.getElementById('nc-logo');
  if (logo) logo.style.display = 'none';

  var dropdownContent = document.getElementById('nc-user-dropdown-content');
  if (dropdownContent) dropdownContent.style.display = 'none';
})();
