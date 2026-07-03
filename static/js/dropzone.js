// Drag & drop de adjuntos. CSP-safe: sin inline. Sube por fetch y recarga.
(function () {
  'use strict';
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';

  Array.prototype.forEach.call(document.querySelectorAll('[data-dropzone]'), function (form) {
    var area = form.querySelector('[data-dropzone-area]');
    var input = form.querySelector('[data-dropzone-input]');
    if (!area || !input) return;

    function upload(files) {
      if (!files || !files.length) return;
      var fd = new FormData();
      var token = form.querySelector('[name=csrfmiddlewaretoken]');
      if (token) fd.append('csrfmiddlewaretoken', token.value);
      for (var i = 0; i < files.length; i++) fd.append('files', files[i]);
      area.classList.add('opacity-50', 'pointer-events-none');
      fetch(form.action, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
        body: fd
      }).then(function () { window.location.reload(); })
        .catch(function () { window.location.reload(); });
    }

    input.addEventListener('change', function () { upload(input.files); });

    ['dragover', 'dragenter'].forEach(function (ev) {
      area.addEventListener(ev, function (e) {
        e.preventDefault();
        area.classList.add('bg-base-200', 'border-primary');
      });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      area.addEventListener(ev, function (e) {
        e.preventDefault();
        area.classList.remove('bg-base-200', 'border-primary');
      });
    });
    area.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files) upload(e.dataTransfer.files);
    });
  });
})();
