/**
 * GYMFORGE — Núcleo compartido del frontend.
 *
 * Expone `window.GF` con utilidades que reutilizan el resto de los módulos:
 * lectura del token CSRF, peticiones fetch con manejo de errores, toasts y
 * control de los paneles laterales.
 *
 * Ningún secreto del backend vive aquí: este código solo consume endpoints
 * públicos y siempre confía en los importes que devuelve el servidor.
 */
(function () {
  'use strict';

  /* --- URLs del backend --------------------------------------------------- */

  /**
   * Las rutas llegan desde el template mediante `json_script`, no por un
   * script en línea: la Content-Security-Policy del sitio prohíbe el JS
   * embebido.
   */
  (function loadUrls() {
    const node = document.getElementById('gf-urls');
    try {
      window.GF_URLS = node ? JSON.parse(node.textContent) : {};
    } catch (error) {
      window.GF_URLS = {};
    }
  })();

  /* --- CSRF -------------------------------------------------------------- */

  /**
   * Lee el token CSRF de la cookie que emite Django.
   * @returns {string} token o cadena vacía si no existe.
   */
  function getCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  /* --- Peticiones -------------------------------------------------------- */

  /**
   * Envía un POST con protección CSRF al backend.
   * @param {string} url
   * @param {Object} data pares clave/valor del formulario.
   * @returns {Promise<Object>} cuerpo JSON de la respuesta.
   * @throws {Error} con el mensaje que devuelve el servidor.
   */
  async function postForm(url, data) {
    const body = new URLSearchParams();
    Object.entries(data).forEach(([key, value]) => body.append(key, value));

    let response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCsrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: body.toString(),
        credentials: 'same-origin',
      });
    } catch (networkError) {
      throw new Error('Sin conexión. Revisa tu red e inténtalo de nuevo.');
    }

    let payload = {};
    try {
      payload = await response.json();
    } catch (parseError) {
      throw new Error('El servidor devolvió una respuesta inesperada.');
    }

    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || 'No pudimos completar la acción.');
    }
    return payload;
  }

  /**
   * Realiza un GET que devuelve JSON.
   * @param {string} url
   * @returns {Promise<Object>}
   */
  async function getJson(url) {
    const response = await fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    });
    if (!response.ok) {
      throw new Error('No pudimos obtener los datos.');
    }
    return response.json();
  }

  /* --- Toasts ------------------------------------------------------------ */

  /**
   * Muestra una notificación efímera.
   * @param {string} message
   * @param {'success'|'error'|'info'} [type='success']
   */
  function toast(message, type) {
    const container = document.getElementById('toasts');
    if (!container || !message) return;

    const element = document.createElement('div');
    element.className = 'toast toast--' + (type || 'success');
    element.setAttribute('role', type === 'error' ? 'alert' : 'status');
    element.textContent = message;
    container.appendChild(element);

    window.setTimeout(function () {
      element.classList.add('is-leaving');
      element.addEventListener('animationend', function () {
        element.remove();
      });
    }, 3600);
  }

  /* --- Estado de carga de los botones ------------------------------------ */

  function setLoading(button, isLoading) {
    if (!button) return;
    button.classList.toggle('is-loading', Boolean(isLoading));
    button.disabled = Boolean(isLoading);
  }

  /* --- Paneles laterales ------------------------------------------------- */

  /** Panel actualmente abierto, para poder cerrarlo con Escape. */
  let openPanel = null;
  /** Elemento que tenía el foco antes de abrir el panel. */
  let lastFocused = null;

  function openDrawer(element) {
    if (!element) return;
    if (openPanel && openPanel !== element) closeDrawer(openPanel);

    lastFocused = document.activeElement;
    element.classList.add('is-open');
    element.setAttribute('aria-hidden', 'false');
    document.body.classList.add('is-locked');
    openPanel = element;

    // Lleva el foco al primer control del panel para no perder el teclado.
    const focusable = element.querySelector(
      'input, button, a[href], select, textarea'
    );
    if (focusable) window.setTimeout(() => focusable.focus(), 60);
  }

  function closeDrawer(element) {
    const target = element || openPanel;
    if (!target) return;

    target.classList.remove('is-open');
    target.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('is-locked');
    if (openPanel === target) openPanel = null;

    if (lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus();
      lastFocused = null;
    }
  }

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && openPanel) closeDrawer(openPanel);
  });

  /* --- Contador del carrito ---------------------------------------------- */

  /**
   * Sincroniza el badge del carrito con el estado que devuelve el servidor.
   * @param {number} count unidades totales.
   */
  function updateCartCount(count) {
    const badge = document.getElementById('cart-count');
    if (!badge) return;

    badge.textContent = count > 99 ? '99+' : String(count);
    badge.hidden = count === 0;

    if (count > 0) {
      badge.classList.add('is-bumped');
      window.setTimeout(() => badge.classList.remove('is-bumped'), 220);
    }
  }

  /* --- Formato ----------------------------------------------------------- */

  /**
   * Formatea un entero como precio chileno.
   * Solo para mostrar: los importes válidos son siempre los del servidor.
   * @param {number} value
   * @returns {string}
   */
  function formatCLP(value) {
    return '$' + Number(value || 0).toLocaleString('es-CL');
  }

  /* --- Inicialización ---------------------------------------------------- */

  document.addEventListener('DOMContentLoaded', function () {
    // Menú móvil.
    const mobileMenu = document.getElementById('mobile-menu');
    document.querySelectorAll('[data-open-menu]').forEach(function (button) {
      button.addEventListener('click', () => openDrawer(mobileMenu));
    });

    // Buscador.
    const search = document.getElementById('search-panel');
    document.querySelectorAll('[data-open-search]').forEach(function (button) {
      button.addEventListener('click', () => openDrawer(search));
    });

    // Mini carrito.
    const minicart = document.getElementById('minicart');
    document.querySelectorAll('[data-open-cart]').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.preventDefault();
        openDrawer(minicart);
        document.dispatchEvent(new CustomEvent('gf:minicart-open'));
      });
    });

    // Cierre por botón o por clic en el fondo oscuro.
    document.querySelectorAll('[data-close-panel]').forEach(function (button) {
      button.addEventListener('click', function () {
        closeDrawer(button.closest('.minicart, .mobile-menu, .search'));
      });
    });

    // Los mensajes del servidor se muestran como toasts.
    document.querySelectorAll('[data-toast]').forEach(function (node) {
      toast(node.dataset.toast, node.dataset.toastType || 'success');
      node.remove();
    });
  });

  /* --- API pública ------------------------------------------------------- */
  window.GF = {
    getCsrfToken: getCsrfToken,
    postForm: postForm,
    getJson: getJson,
    toast: toast,
    setLoading: setLoading,
    openDrawer: openDrawer,
    closeDrawer: closeDrawer,
    updateCartCount: updateCartCount,
    formatCLP: formatCLP,
  };
})();
