/**
 * GYMFORGE — Buscador con sugerencias.
 *
 * Consulta el endpoint público de sugerencias con debounce para no lanzar una
 * petición por cada tecla.
 */
(function () {
  'use strict';

  const GF = window.GF;
  if (!GF) return;

  const MIN_CHARS = 2;
  const DEBOUNCE_MS = 260;

  document.addEventListener('DOMContentLoaded', function () {
    const input = document.getElementById('search-input');
    const results = document.getElementById('search-results');
    if (!input || !results) return;

    const endpoint =
      (window.GF_URLS && window.GF_URLS.searchSuggestions) || '/api/buscar/';

    let timer = null;
    let lastQuery = '';

    function renderEmpty(message) {
      results.innerHTML = '';
      const paragraph = document.createElement('p');
      paragraph.className = 'text-muted';
      paragraph.textContent = message;
      results.appendChild(paragraph);
    }

    function render(items, query) {
      results.innerHTML = '';

      if (!items.length) {
        renderEmpty('Sin resultados para "' + query + '".');
        return;
      }

      items.forEach(function (item) {
        const link = document.createElement('a');
        link.className = 'search__result';
        link.href = item.url;

        const image = document.createElement('img');
        image.src = item.image;
        image.alt = '';
        image.loading = 'lazy';

        const info = document.createElement('div');
        const name = document.createElement('strong');
        // textContent evita inyectar HTML desde el nombre del producto.
        name.textContent = item.name;
        const category = document.createElement('p');
        category.className = 'minicart__meta';
        category.textContent = item.category;
        info.append(name, category);

        const price = document.createElement('span');
        price.className = 'price';
        price.textContent = item.price;

        link.append(image, info, price);
        results.appendChild(link);
      });
    }

    async function search(query) {
      try {
        const payload = await GF.getJson(
          endpoint + '?q=' + encodeURIComponent(query)
        );
        // Descarta respuestas obsoletas si el usuario siguió escribiendo.
        if (query !== lastQuery) return;
        render(payload.results, query);
      } catch (error) {
        renderEmpty('No pudimos completar la búsqueda.');
      }
    }

    input.addEventListener('input', function () {
      const query = input.value.trim();
      lastQuery = query;
      window.clearTimeout(timer);

      if (query.length < MIN_CHARS) {
        results.innerHTML = '';
        return;
      }

      renderEmpty('Buscando…');
      timer = window.setTimeout(() => search(query), DEBOUNCE_MS);
    });
  });
})();
