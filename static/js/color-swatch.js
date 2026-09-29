// Vista previa de los campos de color del formulario de empresa (CSP-safe: sin inline).
// El <span data-color-swatch="<id del input>"> toma el color del input al escribir.
(function () {
  'use strict';
  var HEX = /^#[0-9a-fA-F]{6}$/;
  function paint(input) {
    var swatch = document.querySelector('[data-color-swatch="' + input.id + '"]');
    if (!swatch) return;
    var value = (input.value || '').trim();
    swatch.style.backgroundColor = HEX.test(value) ? value : 'transparent';
  }
  document.querySelectorAll('[data-color-swatch]').forEach(function (swatch) {
    var input = document.getElementById(swatch.getAttribute('data-color-swatch'));
    if (!input) return;
    paint(input);
    input.addEventListener('input', function () { paint(input); });
  });
})();
