/**
 * GYMFORGE — Catálogo.
 *
 * Muestra y oculta el panel de filtros en pantallas pequeñas. En escritorio
 * el panel siempre está visible, así que este código no interviene.
 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    const toggle = document.querySelector('[data-toggle-filters]');
    const panel = document.getElementById('filters');
    if (!toggle || !panel) return;

    const mobileQuery = window.matchMedia('(max-width: 1023px)');

    function applyState() {
      if (mobileQuery.matches) {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        panel.hidden = !expanded;
      } else {
        panel.hidden = false;
      }
    }

    toggle.addEventListener('click', function () {
      const expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
      applyState();
    });

    mobileQuery.addEventListener('change', applyState);

    // Estado inicial: cerrado en móvil, abierto en escritorio.
    toggle.setAttribute('aria-expanded', 'false');
    applyState();
  });
})();
