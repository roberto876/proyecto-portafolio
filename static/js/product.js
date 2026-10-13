/**
 * GYMFORGE — Ficha de producto.
 *
 * Sincroniza los selectores de talla y color con la matriz de variantes que
 * entrega el servidor, deshabilita las combinaciones sin stock y prepara el
 * botón de agregar al carrito.
 *
 * La matriz solo se usa para la experiencia de usuario: el stock definitivo
 * se vuelve a validar en el backend al agregar y al pagar.
 */
(function () {
  'use strict';

  const GF = window.GF;
  if (!GF) return;

  document.addEventListener('DOMContentLoaded', function () {
    const root = document.getElementById('product-detail');
    if (!root) return;

    /** @type {Object<string, {id:number,size:string,color:string,stock:number}>} */
    let variants = {};
    try {
      variants = JSON.parse(
        document.getElementById('variant-data').textContent
      );
    } catch (error) {
      return;
    }

    const sizeButtons = Array.from(root.querySelectorAll('[data-size]'));
    const colorButtons = Array.from(root.querySelectorAll('[data-color]'));
    const addButton = root.querySelector('[data-add-to-cart]');
    const qtyInput = root.querySelector('[data-qty-input]');
    const stockNote = root.querySelector('[data-stock-note]');
    const sizeValue = root.querySelector('[data-selected-size]');
    const colorValue = root.querySelector('[data-selected-color]');

    let selectedSize = null;
    let selectedColor = null;

    /** Devuelve la variante para la combinación indicada, si existe. */
    function findVariant(size, color) {
      return variants[size + '|' + color] || null;
    }

    /** ¿Existe alguna variante con stock para esta talla? */
    function sizeHasStock(size) {
      return Object.values(variants).some(function (variant) {
        return (
          variant.size === size &&
          variant.stock > 0 &&
          (!selectedColor || variant.color === selectedColor)
        );
      });
    }

    /** ¿Existe alguna variante con stock para este color? */
    function colorHasStock(color) {
      return Object.values(variants).some(function (variant) {
        return (
          variant.color === color &&
          variant.stock > 0 &&
          (!selectedSize || variant.size === selectedSize)
        );
      });
    }

    /** Deshabilita las combinaciones imposibles según lo ya elegido. */
    function refreshAvailability() {
      sizeButtons.forEach(function (button) {
        const disabled = !sizeHasStock(button.dataset.size);
        button.disabled = disabled;
        button.setAttribute('aria-disabled', String(disabled));
        if (disabled && button.dataset.size === selectedSize) {
          selectedSize = null;
          button.classList.remove('is-selected');
        }
      });

      colorButtons.forEach(function (button) {
        const disabled = !colorHasStock(button.dataset.color);
        button.disabled = disabled;
        button.setAttribute('aria-disabled', String(disabled));
        if (disabled && button.dataset.color === selectedColor) {
          selectedColor = null;
          button.classList.remove('is-selected');
        }
      });
    }

    /** Actualiza el mensaje de stock y el estado del botón de compra. */
    function refreshSelection() {
      const variant =
        selectedSize && selectedColor
          ? findVariant(selectedSize, selectedColor)
          : null;

      if (sizeValue) sizeValue.textContent = selectedSize || '';
      if (colorValue) colorValue.textContent = selectedColor || '';

      if (!variant) {
        setStock('Selecciona talla y color', '');
        setAddEnabled(false, null);
        setMaxQuantity(1);
        return;
      }

      if (variant.stock <= 0) {
        setStock('Sin stock en esta combinación', 'out');
        setAddEnabled(false, null);
        setMaxQuantity(1);
        return;
      }

      if (variant.stock <= 5) {
        setStock('¡Últimas ' + variant.stock + ' unidades!', 'low');
      } else {
        setStock('En stock — listo para despachar', 'ok');
      }
      setAddEnabled(true, variant.id);
      setMaxQuantity(variant.stock);
    }

    function setStock(message, modifier) {
      if (!stockNote) return;
      stockNote.textContent = message;
      stockNote.className =
        'stock-note' + (modifier ? ' stock-note--' + modifier : '');
    }

    function setAddEnabled(enabled, variantId) {
      if (!addButton) return;
      addButton.disabled = !enabled;
      if (enabled) {
        addButton.dataset.variantId = variantId;
        addButton.textContent = 'Agregar al carrito';
      } else {
        delete addButton.dataset.variantId;
        addButton.textContent = 'Selecciona talla y color';
      }
    }

    /** Ajusta el tope del selector de cantidad al stock real. */
    function setMaxQuantity(stock) {
      if (!qtyInput) return;
      const max = Math.min(stock, Number(qtyInput.dataset.hardMax || 10));
      qtyInput.max = String(max);
      if (Number(qtyInput.value) > max) qtyInput.value = String(max);
    }

    /* --- Eventos --------------------------------------------------------- */

    sizeButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        if (button.disabled) return;
        const size = button.dataset.size;
        selectedSize = selectedSize === size ? null : size;
        sizeButtons.forEach(function (other) {
          other.classList.toggle(
            'is-selected',
            other.dataset.size === selectedSize
          );
          other.setAttribute(
            'aria-pressed',
            String(other.dataset.size === selectedSize)
          );
        });
        refreshAvailability();
        refreshSelection();
      });
    });

    colorButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        if (button.disabled) return;
        const color = button.dataset.color;
        selectedColor = selectedColor === color ? null : color;
        colorButtons.forEach(function (other) {
          other.classList.toggle(
            'is-selected',
            other.dataset.color === selectedColor
          );
          other.setAttribute(
            'aria-pressed',
            String(other.dataset.color === selectedColor)
          );
        });
        refreshAvailability();
        refreshSelection();
      });
    });

    // Selector de cantidad.
    root.querySelectorAll('[data-qty-step]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (!qtyInput) return;
        const next = Number(qtyInput.value) + Number(button.dataset.qtyStep);
        const min = Number(qtyInput.min || 1);
        const max = Number(qtyInput.max || 1);
        if (next < min || next > max) return;
        qtyInput.value = String(next);
      });
    });

    // Agregar al carrito con la variante seleccionada.
    if (addButton) {
      addButton.addEventListener('click', function () {
        const variantId = addButton.dataset.variantId;
        if (!variantId) {
          GF.toast('Selecciona una talla y un color.', 'error');
          return;
        }
        GF.cart.add(variantId, Number(qtyInput ? qtyInput.value : 1), addButton);
      });
    }

    /* --- Galería --------------------------------------------------------- */
    const mainImage = root.querySelector('[data-gallery-main]');
    root.querySelectorAll('[data-gallery-thumb]').forEach(function (thumb) {
      thumb.addEventListener('click', function () {
        if (!mainImage) return;
        mainImage.src = thumb.dataset.galleryThumb;
        root
          .querySelectorAll('[data-gallery-thumb]')
          .forEach(function (other) {
            other.classList.toggle('is-active', other === thumb);
          });
      });
    });

    /* --- Estado inicial -------------------------------------------------- */
    // Si solo hay un color o una talla, se preselecciona para ahorrar un clic.
    const uniqueColors = new Set(colorButtons.map((b) => b.dataset.color));
    if (uniqueColors.size === 1 && colorButtons.length) {
      colorButtons[0].click();
    }
    const uniqueSizes = new Set(sizeButtons.map((b) => b.dataset.size));
    if (uniqueSizes.size === 1 && sizeButtons.length) {
      sizeButtons[0].click();
    }

    refreshAvailability();
    refreshSelection();
  });
})();
