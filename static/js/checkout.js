/**
 * GYMFORGE — Checkout.
 *
 * Filtra las comunas según la región elegida y evita el doble envío del
 * formulario. La validación real ocurre en el servidor: este código solo
 * mejora la experiencia.
 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    const regionSelect = document.getElementById('id_region');
    const communeSelect = document.getElementById('id_commune');

    if (regionSelect && communeSelect) {
      /** @type {Object<string, string[]>} */
      let regions = {};
      const dataNode = document.getElementById('regions-data');
      if (dataNode) {
        try {
          regions = JSON.parse(dataNode.textContent);
        } catch (error) {
          regions = {};
        }
      }

      // Valor ya elegido (por ejemplo al reenviar el formulario con errores).
      const preselected = communeSelect.dataset.selected || '';

      function fillCommunes(region, selected) {
        const communes = regions[region] || [];
        communeSelect.innerHTML = '';

        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = communes.length
          ? 'Selecciona una comuna'
          : 'Selecciona primero una región';
        communeSelect.appendChild(placeholder);

        communes.forEach(function (commune) {
          const option = document.createElement('option');
          option.value = commune;
          option.textContent = commune;
          if (commune === selected) option.selected = true;
          communeSelect.appendChild(option);
        });

        communeSelect.disabled = communes.length === 0;
      }

      fillCommunes(regionSelect.value, preselected);
      regionSelect.addEventListener('change', function () {
        fillCommunes(regionSelect.value, '');
      });
    }

    // Un doble clic en "Pagar" no debe crear dos órdenes.
    const form = document.getElementById('checkout-form');
    if (form) {
      let submitted = false;
      form.addEventListener('submit', function (event) {
        if (submitted) {
          event.preventDefault();
          return;
        }
        submitted = true;
        const button = form.querySelector('[type="submit"]');
        if (button && window.GF) {
          window.GF.setLoading(button, true);
          // El botón deshabilitado no se envía: se marca tras el submit.
          window.setTimeout(function () {
            button.disabled = true;
          }, 0);
        }
      });
    }
  });
})();
