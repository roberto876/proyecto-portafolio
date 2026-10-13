/**
 * GYMFORGE — Redirección a Webpay.
 *
 * Envía automáticamente el formulario que entrega el token a Transbank. Si el
 * JavaScript está deshabilitado, el usuario dispone del botón manual, así que
 * el flujo nunca queda bloqueado.
 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('webpay-form');
    if (!form) return;

    // Pequeño margen para que se vea el mensaje antes de salir del sitio.
    window.setTimeout(function () {
      form.submit();
    }, 900);
  });
})();
