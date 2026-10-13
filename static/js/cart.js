/**
 * GYMFORGE — Carrito.
 *
 * Gestiona agregar, actualizar y eliminar líneas mediante fetch, y refresca
 * el mini-carrito. Todos los importes mostrados provienen de la respuesta del
 * servidor: el navegador nunca calcula totales.
 */
(function () {
  'use strict';

  const GF = window.GF;
  if (!GF) return;

  const URLS = window.GF_URLS || {};

  /* --- Renderizado del mini carrito -------------------------------------- */

  /**
   * Pinta el contenido del panel lateral con el estado recibido.
   * @param {Object} cart estado serializado del carrito.
   */
  function renderMinicart(cart) {
    const body = document.getElementById('minicart-body');
    const foot = document.getElementById('minicart-foot');
    if (!body) return;

    GF.updateCartCount(cart.count);

    if (!cart.items.length) {
      body.innerHTML =
        '<div class="empty-state">' +
        '<p>Tu carrito está vacío.</p>' +
        '<a class="btn btn--dark" href="' +
        (URLS.productList || '/productos/') +
        '">Ver productos</a></div>';
      if (foot) foot.hidden = true;
      return;
    }

    if (foot) foot.hidden = false;
    body.innerHTML = '';

    cart.items.forEach(function (item) {
      const line = document.createElement('div');
      line.className = 'minicart__line';

      const link = document.createElement('a');
      link.href = item.url;
      const image = document.createElement('img');
      image.src = item.image;
      image.alt = item.name;
      image.loading = 'lazy';
      link.appendChild(image);

      const info = document.createElement('div');

      const name = document.createElement('a');
      name.className = 'minicart__name';
      name.href = item.url;
      // textContent evita cualquier inyección de HTML en el nombre.
      name.textContent = item.name;

      const meta = document.createElement('p');
      meta.className = 'minicart__meta';
      meta.textContent =
        item.size + ' · ' + item.color + ' · ' + item.quantity + ' u.';

      const price = document.createElement('p');
      price.className = 'minicart__meta';
      price.textContent = item.subtotal_formatted;

      info.append(name, meta, price);

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'icon-btn';
      remove.setAttribute('aria-label', 'Eliminar ' + item.name);
      remove.dataset.removeVariant = item.variant_id;
      remove.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>';

      line.append(link, info, remove);
      body.appendChild(line);
    });

    updateTotals(cart);
  }

  /** Actualiza los importes del pie del mini carrito. */
  function updateTotals(cart) {
    const map = {
      'minicart-subtotal': cart.subtotal_formatted,
      'minicart-shipping': cart.shipping_formatted,
      'minicart-total': cart.total_formatted,
    };
    Object.entries(map).forEach(function ([id, value]) {
      const node = document.getElementById(id);
      if (node) node.textContent = value;
    });
  }

  /** Descarga el estado actual del carrito y lo pinta. */
  async function refreshMinicart() {
    try {
      const payload = await GF.getJson(URLS.cartState || '/carrito/estado/');
      renderMinicart(payload.cart);
    } catch (error) {
      GF.toast('No pudimos cargar tu carrito.', 'error');
    }
  }

  /* --- Acciones ---------------------------------------------------------- */

  /**
   * Agrega una variante al carrito.
   * @param {string|number} variantId
   * @param {number} quantity
   * @param {HTMLElement} [button] botón que dispara la acción.
   */
  async function addToCart(variantId, quantity, button) {
    GF.setLoading(button, true);
    try {
      const payload = await GF.postForm(URLS.cartAdd || '/carrito/agregar/', {
        variant_id: variantId,
        quantity: quantity || 1,
      });
      renderMinicart(payload.cart);
      GF.toast(payload.message || 'Producto agregado.');
      GF.openDrawer(document.getElementById('minicart'));
    } catch (error) {
      GF.toast(error.message, 'error');
    } finally {
      GF.setLoading(button, false);
    }
  }

  /** Elimina una línea y recarga la página del carrito si estamos en ella. */
  async function removeFromCart(variantId, button) {
    GF.setLoading(button, true);
    try {
      const payload = await GF.postForm(
        URLS.cartRemove || '/carrito/eliminar/',
        { variant_id: variantId }
      );
      renderMinicart(payload.cart);
      GF.toast(payload.message || 'Producto eliminado.');
      if (document.body.dataset.page === 'cart') window.location.reload();
    } catch (error) {
      GF.toast(error.message, 'error');
    } finally {
      GF.setLoading(button, false);
    }
  }

  /** Cambia la cantidad de una línea existente. */
  async function updateQuantity(variantId, quantity, lineElement) {
    try {
      const payload = await GF.postForm(
        URLS.cartUpdate || '/carrito/actualizar/',
        { variant_id: variantId, quantity: quantity }
      );
      renderMinicart(payload.cart);
      syncCartPage(payload.cart, variantId, lineElement);
    } catch (error) {
      GF.toast(error.message, 'error');
      // Restaura la cantidad real desde el servidor tras un rechazo.
      refreshCartPage();
    }
  }

  /** Refleja en la página del carrito los importes recalculados. */
  function syncCartPage(cart, variantId, lineElement) {
    const map = {
      'cart-subtotal': cart.subtotal_formatted,
      'cart-shipping': cart.shipping_formatted,
      'cart-total': cart.total_formatted,
    };
    Object.entries(map).forEach(function ([id, value]) {
      const node = document.getElementById(id);
      if (node) node.textContent = value;
    });

    const item = cart.items.find(function (candidate) {
      return String(candidate.variant_id) === String(variantId);
    });
    if (item && lineElement) {
      const subtotal = lineElement.querySelector('[data-line-subtotal]');
      if (subtotal) subtotal.textContent = item.subtotal_formatted;
      const input = lineElement.querySelector('[data-qty-input]');
      if (input) input.value = item.quantity;
    }

    updateFreeShippingBar(cart);
  }

  /** Actualiza la barra de progreso hacia el envío gratis. */
  function updateFreeShippingBar(cart) {
    const bar = document.getElementById('free-shipping-bar');
    const label = document.getElementById('free-shipping-label');
    if (!bar || !label) return;

    const threshold = Number(bar.dataset.threshold || 0);
    if (!threshold) return;

    const progress = Math.min((cart.subtotal / threshold) * 100, 100);
    bar.style.width = progress + '%';
    label.textContent = cart.has_free_shipping
      ? '¡Tienes envío gratis!'
      : 'Te faltan ' +
        GF.formatCLP(cart.amount_for_free_shipping) +
        ' para el envío gratis';
  }

  function refreshCartPage() {
    if (document.body.dataset.page === 'cart') window.location.reload();
  }

  /* --- Enlaces con el DOM ------------------------------------------------ */

  document.addEventListener('DOMContentLoaded', function () {
    // Botones "Agregar al carrito" de las tarjetas de producto.
    document.addEventListener('click', function (event) {
      const addButton = event.target.closest('[data-add-variant]');
      if (addButton) {
        event.preventDefault();
        addToCart(
          addButton.dataset.addVariant,
          Number(addButton.dataset.quantity || 1),
          addButton
        );
        return;
      }

      const removeButton = event.target.closest('[data-remove-variant]');
      if (removeButton) {
        event.preventDefault();
        removeFromCart(removeButton.dataset.removeVariant, removeButton);
      }
    });

    // Selectores de cantidad de la página del carrito.
    document.querySelectorAll('[data-cart-line]').forEach(function (line) {
      const input = line.querySelector('[data-qty-input]');
      const variantId = line.dataset.cartLine;
      if (!input) return;

      line.querySelectorAll('[data-qty-step]').forEach(function (button) {
        button.addEventListener('click', function () {
          const step = Number(button.dataset.qtyStep);
          const next = Number(input.value) + step;
          const min = Number(input.min || 1);
          const max = Number(input.max || 10);
          if (next < min || next > max) return;
          input.value = next;
          updateQuantity(variantId, next, line);
        });
      });

      input.addEventListener('change', function () {
        const min = Number(input.min || 1);
        const max = Number(input.max || 10);
        let value = Number(input.value);
        if (!Number.isFinite(value) || value < min) value = min;
        if (value > max) value = max;
        input.value = value;
        updateQuantity(variantId, value, line);
      });
    });

    // El mini carrito se carga la primera vez que se abre.
    let minicartLoaded = false;
    document.addEventListener('gf:minicart-open', function () {
      if (!minicartLoaded) {
        minicartLoaded = true;
        refreshMinicart();
      }
    });
  });

  window.GF.cart = {
    add: addToCart,
    remove: removeFromCart,
    refresh: refreshMinicart,
  };
})();
