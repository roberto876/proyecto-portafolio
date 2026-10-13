"""Herramientas para crear variantes rápido desde el panel de administración.

Cargar un producto con 3 colores y 6 tallas son 18 filas: a mano es lento y
propenso a errores. Aquí se generan todas de una vez.
"""
from .models import ProductVariant

#: Colores habituales en español -> código hexadecimal para la muestra.
COLOR_HEX = {
    'negro': '#111111',
    'blanco': '#f5f5f5',
    'gris': '#8a8a8a',
    'gris claro': '#c9c9c9',
    'gris oscuro': '#4a4a4a',
    'gris grafito': '#4a4a4a',
    'grafito': '#4a4a4a',
    'rojo': '#d62828',
    'burdeo': '#7b1e2b',
    'vino': '#7b1e2b',
    'azul': '#1e5bff',
    'azul marino': '#1b2a4a',
    'azul electrico': '#1e5bff',
    'azul eléctrico': '#1e5bff',
    'celeste': '#7cc4f2',
    'verde': '#2e9e44',
    'verde lima': '#c8ff2e',
    'verde militar': '#4a5a3a',
    'verde oliva': '#6b7a3a',
    'amarillo': '#f5d000',
    'naranjo': '#ff7a00',
    'naranja': '#ff7a00',
    'rosado': '#f4a6c1',
    'rosa': '#f4a6c1',
    'fucsia': '#e0218a',
    'morado': '#6b3fa0',
    'lila': '#9b7bd4',
    'cafe': '#6f4e37',
    'café': '#6f4e37',
    'beige': '#d9c9b0',
    'arena': '#d9c9b0',
    'crema': '#f3ead8',
    'coral': '#ff6b5a',
    'turquesa': '#1abc9c',
}
DEFAULT_HEX = '#999999'


def guess_color_hex(name: str) -> str:
    """Adivina el hexadecimal de un color por su nombre. Gris si no lo conoce."""
    return COLOR_HEX.get(' '.join(name.lower().split()), DEFAULT_HEX)


def parse_colors(text: str) -> list[str]:
    """Convierte «negro, Blanco;azul marino» en ['Negro', 'Blanco', 'Azul marino']."""
    raw = text.replace(';', ',').replace('\n', ',').split(',')
    colors: list[str] = []
    for chunk in raw:
        name = ' '.join(chunk.split())
        if not name:
            continue
        name = name[0].upper() + name[1:]
        if name.lower() not in {c.lower() for c in colors}:
            colors.append(name[:50])
    return colors


def create_variant_grid(product, sizes, colors, stock: int) -> int:
    """Crea todas las combinaciones talla×color que falten. Devuelve cuántas.

    Las combinaciones que ya existen no se tocan: su stock real se respeta.
    """
    created = 0
    for color in colors:
        for size in sizes:
            _, was_created = ProductVariant.objects.get_or_create(
                product=product,
                size=size,
                color=color,
                defaults={'color_hex': guess_color_hex(color), 'stock': stock},
            )
            created += int(was_created)
    return created
