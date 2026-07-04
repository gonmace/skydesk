// Cuando el login de SkyDesk se carga dentro del iframe de Nextcloud (External Sites),
// se oculta el formulario local y se fuerza el SSO a romper el frame: un click normal
// dentro del iframe intentaría cargar la página de autorización de Nextcloud *dentro*
// del iframe, cosa que el propio Nextcloud bloquea con su X-Frame-Options. target="_top"
// navega la pestaña completa; accounts.views.nextcloud_login/_callback usan `embedded=1`
// para saber que deben devolver al usuario a Nextcloud (NEXTCLOUD_RETURN_URL) al terminar.
(function () {
  if (window.self === window.top) return; // standalone: no tocar nada

  var localLogin = document.getElementById('nc-local-login');
  var divider = document.getElementById('nc-divider');
  var ncLink = document.getElementById('nc-login-link');

  if (localLogin) localLogin.style.display = 'none';
  if (divider) divider.style.display = 'none';

  if (ncLink) {
    ncLink.target = '_top';
    var url = new URL(ncLink.href, window.location.origin);
    url.searchParams.set('embedded', '1');
    ncLink.href = url.toString();
  }
})();
