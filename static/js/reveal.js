/**
 * GYMFORGE — Motor de animación por scroll.
 *
 * Implementa las revelaciones y el parallax con IntersectionObserver y CSS
 * puro, sin librerías externas. Se evita cargar GSAP desde un CDN porque la
 * Content-Security-Policy del sitio solo admite scripts propios: en una
 * tienda que procesa pagos, abrir `script-src` a terceros no compensa.
 *
 * Reglas de rendimiento aplicadas:
 * - Solo se animan `transform`, `opacity`, `filter` y `clip-path`.
 * - `will-change` se retira en cuanto termina la animación.
 * - El parallax se actualiza dentro de `requestAnimationFrame`.
 * - En pantallas táctiles y con `prefers-reduced-motion` se desactiva todo.
 */
(function () {
  'use strict';

  const prefersReducedMotion = window.matchMedia(
    '(prefers-reduced-motion: reduce)'
  ).matches;
  const isCoarsePointer = window.matchMedia('(pointer: coarse)').matches;

  /* --- Revelado al entrar en pantalla ------------------------------------ */

  /**
   * Revela los elementos marcados con `data-reveal` cuando entran en el
   * viewport. El retraso escalonado se declara con `--reveal-delay`.
   */
  function initReveal() {
    const items = document.querySelectorAll('[data-reveal]');
    if (!items.length) return;

    if (prefersReducedMotion) {
      items.forEach((item) => item.classList.add('is-revealed'));
      return;
    }

    const observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;

          const element = entry.target;
          element.style.willChange = 'transform, opacity';
          element.classList.add('is-revealed');

          // Se libera la capa de composición al terminar la transición.
          element.addEventListener(
            'transitionend',
            function () {
              element.style.willChange = '';
            },
            { once: true }
          );

          observer.unobserve(element);
        });
      },
      { rootMargin: '0px 0px -12% 0px', threshold: 0.12 }
    );

    items.forEach(function (item, index) {
      // Escalonado automático dentro de cada grupo de hermanos.
      if (!item.style.getPropertyValue('--reveal-delay')) {
        const position = Number(item.dataset.revealIndex ?? index % 8);
        item.style.setProperty('--reveal-delay', position * 70 + 'ms');
      }
      observer.observe(item);
    });
  }

  /* --- Parallax por capas ------------------------------------------------ */

  /**
   * Desplaza los elementos `data-depth` a distinta velocidad para crear
   * profundidad. Los factores siguen la escala del sistema de capas.
   */
  const DEPTH_SPEED = { 0: 0.1, 1: 0.25, 2: 0.5, 3: 0.8, 4: 1, 5: 1.2 };

  function initParallax() {
    // El parallax se desactiva en táctil: cuesta batería y aporta poco.
    if (prefersReducedMotion || isCoarsePointer) return;

    const layers = Array.from(document.querySelectorAll('[data-depth]'));
    if (!layers.length) return;

    let ticking = false;
    let visible = new Set();

    const observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          visible.add(entry.target);
          entry.target.style.willChange = 'transform';
        } else {
          visible.delete(entry.target);
          entry.target.style.willChange = '';
        }
      });
    });
    layers.forEach((layer) => observer.observe(layer));

    function update() {
      const viewportHeight = window.innerHeight;

      visible.forEach(function (layer) {
        const depth = Number(layer.dataset.depth);
        const speed = DEPTH_SPEED[depth];
        if (speed === undefined || speed === 1) return;

        const rect = layer.getBoundingClientRect();
        // Distancia al centro del viewport, normalizada.
        const progress = (rect.top + rect.height / 2 - viewportHeight / 2)
          / viewportHeight;
        const shift = progress * (1 - speed) * 100;

        layer.style.transform = 'translate3d(0,' + shift.toFixed(2) + 'px,0)';
      });

      ticking = false;
    }

    function onScroll() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(update);
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    update();
  }

  /* --- Encabezado que reacciona al scroll -------------------------------- */

  function initHeaderState() {
    const header = document.querySelector('.header');
    if (!header) return;

    let ticking = false;
    function update() {
      header.classList.toggle('is-scrolled', window.scrollY > 12);
      ticking = false;
    }

    window.addEventListener(
      'scroll',
      function () {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(update);
      },
      { passive: true }
    );
    update();
  }

  /* --- Arranque ---------------------------------------------------------- */

  document.addEventListener('DOMContentLoaded', function () {
    initReveal();
    initParallax();
    initHeaderState();
  });
})();
