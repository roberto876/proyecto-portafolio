"""Carga un catálogo de demostración.

Uso::

    python manage.py seed_data            # crea o actualiza el catálogo demo
    python manage.py seed_data --flush    # borra el catálogo antes de crearlo

El comando es idempotente: ejecutarlo dos veces no duplica productos.

Las imágenes son fotografías de Unsplash servidas desde su CDN, cuya licencia
permite el uso comercial y sin atribución obligatoria. Se guardan como URL
absolutas porque en un entorno serverless el filesystem local no sirve como
almacenamiento persistente. Para producción real, reemplaza estas URL por las
de tu propio bucket (por ejemplo Supabase Storage) desde el panel de admin.
"""
import random

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from store.models import Category, Gender, Product, ProductImage, ProductVariant, Size

#: Base del CDN de Unsplash. Los parámetros piden un recorte vertical
#: optimizado, adecuado para las tarjetas de producto (proporción 3:4).
CDN = 'https://images.unsplash.com/{photo}?w={w}&h={h}&q=80&auto=format&fit=crop'


def image(photo: str, width: int = 900, height: int = 1200) -> str:
    return CDN.format(photo=photo, w=width, h=height)


# --- Paleta de colores reutilizable ---------------------------------------
COLORS = {
    'Negro': '#111111',
    'Blanco': '#f5f5f5',
    'Gris grafito': '#4a4a4a',
    'Verde lima': '#c8ff2e',
    'Azul eléctrico': '#1e5bff',
    'Burdeo': '#7b1e2b',
    'Verde militar': '#4a5a3a',
    'Coral': '#ff6b5a',
    'Lila': '#9b7bd4',
    'Arena': '#d9c9b0',
}

STANDARD_SIZES = [Size.XS, Size.S, Size.M, Size.L, Size.XL, Size.XXL]
CORE_SIZES = [Size.S, Size.M, Size.L, Size.XL]
ONE_SIZE = [Size.UNICA]

# --- Categorías ------------------------------------------------------------
CATEGORIES = [
    ('Poleras', 'Poleras técnicas de secado rápido para entrenar sin peso extra.',
     'photo-1521804906057-1df8fdb718b7'),
    ('Shorts', 'Shorts con libertad de movimiento y bolsillos funcionales.',
     'photo-1517838277536-f5f99be501cd'),
    ('Calzas y leggings', 'Compresión progresiva y cintura alta que no se baja.',
     'photo-1518310383802-640c2de311b2'),
    ('Polerones', 'Capas medias para el calentamiento y el after gym.',
     'photo-1556817411-31ae72fa3ea0'),
    ('Tops deportivos', 'Sujeción de impacto medio y alto, sin costuras que rocen.',
     'photo-1571945153237-4929e783af4a'),
    ('Conjuntos', 'Sets coordinados listos para entrenar y salir.',
     'photo-1483721310020-03333e577078'),
    ('Accesorios', 'Lo que completa el equipo: bolsos, cinturones y guantes.',
     'photo-1517343985841-f8b2d66e010b'),
]

# --- Productos -------------------------------------------------------------
# (nombre, categoría, género, precio, precio_anterior, destacado, descripción,
#  imágenes, colores, tallas)
PRODUCTS = [
    (
        'Polera Performance Dry', 'Poleras', Gender.HOMBRE, 19990, 27990, True,
        'Polera de entrenamiento en poliéster reciclado con tecnología de secado '
        'rápido. Costuras planas en hombros y costados para evitar rozaduras en '
        'series largas. Corte regular que no restringe el press de banca.',
        ['photo-1521804906057-1df8fdb718b7', 'photo-1503341504253-dff4815485f1'],
        ['Negro', 'Blanco', 'Verde lima'], STANDARD_SIZES,
    ),
    (
        'Polera Oversize Training', 'Poleras', Gender.UNISEX, 22990, None, True,
        'Corte oversize en algodón peinado con mezcla técnica. Cae recta, no se '
        'pega al cuerpo y aguanta el ciclo de lavado diario sin deformarse.',
        ['photo-1503341504253-dff4815485f1', 'photo-1618886614638-80e3c103d31a'],
        ['Negro', 'Arena', 'Verde militar'], STANDARD_SIZES,
    ),
    (
        'Polera Sin Mangas Iron', 'Poleras', Gender.HOMBRE, 16990, 21990, False,
        'Musculosa de sisa amplia para trabajo de hombro y espalda. Tejido '
        'liviano de 140 g/m² con acabado antiolor.',
        ['photo-1594381898411-846e7d193883'],
        ['Negro', 'Gris grafito'], CORE_SIZES,
    ),
    (
        'Polera Compresión Base', 'Poleras', Gender.HOMBRE, 24990, None, False,
        'Primera capa de compresión que mejora el retorno venoso y mantiene la '
        'temperatura estable. Ideal bajo el polerón en invierno.',
        ['photo-1547919307-1ecb10702e6f'],
        ['Negro', 'Azul eléctrico'], CORE_SIZES,
    ),
    (
        'Short Training 7"', 'Shorts', Gender.HOMBRE, 21990, 29990, True,
        'Short de 7 pulgadas con liner interior, cintura elástica con cordón y '
        'bolsillo con cierre para el teléfono. El favorito para pierna y cardio.',
        ['photo-1517838277536-f5f99be501cd', 'photo-1526506118085-60ce8714f8c5'],
        ['Negro', 'Gris grafito', 'Verde militar'], STANDARD_SIZES,
    ),
    (
        'Short Runner Ultralight', 'Shorts', Gender.HOMBRE, 18990, None, False,
        'Short de running de 5 pulgadas en tejido ripstop de 90 g. Prácticamente '
        'no se siente y seca en minutos.',
        ['photo-1526506118085-60ce8714f8c5'],
        ['Negro', 'Azul eléctrico', 'Coral'], CORE_SIZES,
    ),
    (
        'Short Biker High Waist', 'Shorts', Gender.MUJER, 19990, 24990, True,
        'Biker de cintura alta y largo medio con compresión suave. No transparenta '
        'en sentadilla: probado en peso muerto con barra.',
        ['photo-1518310383802-640c2de311b2', 'photo-1620188467120-5042ed1eb5da'],
        ['Negro', 'Burdeo', 'Lila'], STANDARD_SIZES,
    ),
    (
        'Calza Sculpt High Rise', 'Calzas y leggings', Gender.MUJER, 32990, 44990, True,
        'Calza de cintura alta con panel de compresión abdominal y costura en V '
        'trasera. Tejido de doble capa opaco garantizado.',
        ['photo-1620188467120-5042ed1eb5da', 'photo-1571945153237-4929e783af4a'],
        ['Negro', 'Verde militar', 'Burdeo'], STANDARD_SIZES,
    ),
    (
        'Calza 7/8 Seamless', 'Calzas y leggings', Gender.MUJER, 29990, None, True,
        'Tejido sin costuras laterales, con zonas de ventilación en la corva. '
        'Largo 7/8 que funciona con cualquier zapatilla.',
        ['photo-1602143407151-7111542de6e8'],
        ['Negro', 'Lila', 'Arena'], STANDARD_SIZES,
    ),
    (
        'Legging Térmico Winter', 'Calzas y leggings', Gender.MUJER, 34990, 42990, False,
        'Forro interior afelpado para entrenar al aire libre en invierno. '
        'Cintura con bolsillo lateral para llaves.',
        ['photo-1512496015851-a90fb38ba796'],
        ['Negro', 'Gris grafito'], CORE_SIZES,
    ),
    (
        'Polerón Hoodie Heavyweight', 'Polerones', Gender.UNISEX, 44990, 59990, True,
        'Polerón de 420 g/m² con interior perchado, capucha forrada de doble capa '
        'y puños acanalados que no se sueltan. La capa que te pones todo el año.',
        ['photo-1556817411-31ae72fa3ea0', 'photo-1591195853828-11db59a44f6b'],
        ['Negro', 'Gris grafito', 'Verde militar'], STANDARD_SIZES,
    ),
    (
        'Polerón Media Cremallera', 'Polerones', Gender.HOMBRE, 39990, None, False,
        'Media cremallera con cuello alto para el calentamiento. Tejido técnico '
        'que corta el viento sin dar calor de más.',
        ['photo-1591195853828-11db59a44f6b'],
        ['Negro', 'Azul eléctrico'], CORE_SIZES,
    ),
    (
        'Polerón Crop Studio', 'Polerones', Gender.MUJER, 37990, 45990, False,
        'Corte crop con caída holgada, pensado para usar sobre el top. Algodón '
        'orgánico con mezcla técnica.',
        ['photo-1515886657613-9f3515b0c78f'],
        ['Arena', 'Negro', 'Lila'], CORE_SIZES,
    ),
    (
        'Top Impacto Alto Lock', 'Tops deportivos', Gender.MUJER, 24990, 32990, True,
        'Sujeción de impacto alto para running y salto. Espalda cruzada ajustable '
        'y copas removibles.',
        ['photo-1571945153237-4929e783af4a', 'photo-1518310383802-640c2de311b2'],
        ['Negro', 'Coral', 'Verde lima'], STANDARD_SIZES,
    ),
    (
        'Top Seamless Ribbed', 'Tops deportivos', Gender.MUJER, 19990, None, False,
        'Tejido acanalado sin costuras, impacto medio. Combina con la calza 7/8 '
        'del mismo tejido.',
        ['photo-1602143407151-7111542de6e8'],
        ['Negro', 'Arena', 'Lila'], CORE_SIZES,
    ),
    (
        'Top Cross Back Light', 'Tops deportivos', Gender.MUJER, 17990, 22990, False,
        'Impacto bajo para yoga y movilidad. Tirantes cruzados que no se salen '
        'del hombro.',
        ['photo-1512496015851-a90fb38ba796'],
        ['Blanco', 'Negro', 'Burdeo'], CORE_SIZES,
    ),
    (
        'Conjunto Training Duo', 'Conjuntos', Gender.HOMBRE, 54990, 74990, True,
        'Set de polera técnica y short de 7 pulgadas en el mismo tejido. '
        'Llega listo para entrenar, sin pensar en combinaciones.',
        ['photo-1483721310020-03333e577078', 'photo-1517838277536-f5f99be501cd'],
        ['Negro', 'Gris grafito'], STANDARD_SIZES,
    ),
    (
        'Conjunto Seamless Studio', 'Conjuntos', Gender.MUJER, 59990, 79990, True,
        'Top y calza sin costuras del mismo tejido acanalado. Compresión pareja '
        'y opacidad garantizada.',
        ['photo-1607962837359-5e7e89f86776', 'photo-1620188467120-5042ed1eb5da'],
        ['Negro', 'Arena', 'Verde militar'], STANDARD_SIZES,
    ),
    (
        'Conjunto Oversize Weekend', 'Conjuntos', Gender.UNISEX, 64990, None, False,
        'Polerón y jogger de corte holgado en algodón pesado. Para el after gym '
        'y los días de descanso activo.',
        ['photo-1618886614638-80e3c103d31a'],
        ['Gris grafito', 'Negro'], CORE_SIZES,
    ),
    (
        'Bolso Duffel 35L', 'Accesorios', Gender.UNISEX, 39990, 49990, True,
        'Bolso de 35 litros con compartimento ventilado para zapatillas, bolsillo '
        'húmedo aislado y base reforzada. Cabe el equipo completo del día.',
        ['photo-1517343985841-f8b2d66e010b', 'photo-1553062407-98eeb64c6a62'],
        ['Negro', 'Verde militar'], ONE_SIZE,
    ),
    (
        'Cinturón de Levantamiento', 'Accesorios', Gender.UNISEX, 34990, None, True,
        'Cinturón de 10 mm con hebilla de doble pin. Soporte lumbar firme para '
        'sentadilla y peso muerto pesado.',
        ['photo-1584464491033-06628f3a6b7b'],
        ['Negro'], [Size.S, Size.M, Size.L, Size.XL],
    ),
    (
        'Guantes Grip Pro', 'Accesorios', Gender.UNISEX, 14990, 19990, False,
        'Palma de cuero sintético con refuerzo antideslizante y muñequera '
        'integrada. Protegen la mano en dominadas y remo.',
        ['photo-1550345332-09e3ac987658'],
        ['Negro', 'Gris grafito'], [Size.S, Size.M, Size.L],
    ),
    (
        'Botella Térmica 750 ml', 'Accesorios', Gender.UNISEX, 17990, None, False,
        'Acero inoxidable de doble pared: mantiene el frío 24 horas. Tapa a '
        'prueba de filtraciones y boca ancha para hielo.',
        ['photo-1602143407151-7111542de6e8'],
        ['Negro', 'Verde lima', 'Blanco'], ONE_SIZE,
    ),
    (
        'Calcetines Training Pack x3', 'Accesorios', Gender.UNISEX, 12990, 15990, False,
        'Pack de tres pares con arco de compresión, refuerzo en talón y punta, '
        'y canal de ventilación en el empeine.',
        ['photo-1560243563-062bfc001d68'],
        ['Negro', 'Blanco'], [Size.S, Size.M, Size.L],
    ),
    (
        'Polera Tech Mesh', 'Poleras', Gender.MUJER, 20990, None, False,
        'Paneles de malla en espalda y costados para sesiones de alta intensidad. '
        'Corte entallado sin apretar.',
        ['photo-1487222477894-8943e31ef7b2'],
        ['Blanco', 'Negro', 'Coral'], CORE_SIZES,
    ),
    (
        'Jogger Tapered Active', 'Shorts', Gender.HOMBRE, 36990, 46990, False,
        'Jogger de corte tapered con tobillo elastizado y bolsillos con cierre. '
        'Sirve para entrenar y para el resto del día.',
        ['photo-1552902865-b72c031ac5ea'],
        ['Negro', 'Gris grafito', 'Verde militar'], STANDARD_SIZES,
    ),
    (
        'Cortavientos Packable', 'Polerones', Gender.UNISEX, 42990, 54990, False,
        'Chaqueta ultraliviana que se guarda en su propio bolsillo. Repelente al '
        'agua y con capucha ajustable.',
        ['photo-1622470953794-aa9c70b0fb9d'],
        ['Negro', 'Azul eléctrico'], CORE_SIZES,
    ),
    (
        'Top Deportivo Longline', 'Tops deportivos', Gender.MUJER, 22990, None, False,
        'Top largo de impacto medio con banda inferior ancha que no se enrolla. '
        'Se puede usar solo o bajo la polera.',
        ['photo-1613852348851-df1739db8201'],
        ['Negro', 'Arena', 'Burdeo'], CORE_SIZES,
    ),
]


class Command(BaseCommand):
    help = 'Crea el catálogo de demostración (categorías, productos y variantes).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush', action='store_true',
            help='Elimina el catálogo existente antes de crear el nuevo.',
        )
        parser.add_argument(
            '--seed', type=int, default=42,
            help='Semilla del generador de stock, para resultados reproducibles.',
        )
        parser.add_argument(
            '--if-empty', action='store_true',
            help='Solo carga la demo si no hay ningún producto. Protege un '
                 'catálogo real de ser sobrescrito.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['if_empty'] and Product.objects.exists():
            self.stdout.write('Ya hay productos: no se carga la demostración.')
            return

        random.seed(options['seed'])

        if options['flush']:
            self._flush()

        categories = self._create_categories()
        self._create_products(categories)

        self.stdout.write(self.style.SUCCESS(
            f'\nCatálogo listo: {Category.objects.count()} categorías, '
            f'{Product.objects.count()} productos y '
            f'{ProductVariant.objects.count()} variantes.'
        ))
        self.stdout.write(
            'Crea un administrador con: python manage.py createsuperuser'
        )

    def _flush(self):
        """Borra el catálogo. Las órdenes conservan su copia histórica."""
        deleted = Product.objects.count()
        ProductVariant.objects.all().delete()
        ProductImage.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()
        self.stdout.write(self.style.WARNING(
            f'Catálogo anterior eliminado ({deleted} productos).'
        ))

    def _create_categories(self) -> dict[str, Category]:
        categories = {}
        for order, (name, description, photo) in enumerate(CATEGORIES):
            category, created = Category.objects.update_or_create(
                slug=slugify(name),
                defaults={
                    'name': name,
                    'description': description,
                    'image': image(photo, 600, 800),
                    'is_active': True,
                    'sort_order': order,
                },
            )
            categories[name] = category
            self.stdout.write(
                f'  {"+" if created else "~"} Categoría: {name}'
            )
        return categories

    def _create_products(self, categories: dict[str, Category]):
        for row in PRODUCTS:
            (name, category_name, gender, price, compare_price, featured,
             description, photos, colors, sizes) = row

            product, created = Product.objects.update_or_create(
                slug=slugify(name),
                defaults={
                    'name': name,
                    'category': categories[category_name],
                    'gender': gender,
                    'price': price,
                    'compare_price': compare_price,
                    'description': description,
                    'main_image': image(photos[0]),
                    'is_active': True,
                    'is_featured': featured,
                },
            )

            # Imágenes adicionales de la galería.
            product.images.all().delete()
            ProductImage.objects.bulk_create([
                ProductImage(
                    product=product,
                    image=image(photo),
                    alt_text=f'{name} — vista {index + 1}',
                    sort_order=index,
                )
                for index, photo in enumerate(photos[1:], start=1)
            ])

            self._create_variants(product, colors, sizes)
            self.stdout.write(
                f'  {"+" if created else "~"} {name} '
                f'({len(colors)}×{len(sizes)} variantes)'
            )

    def _create_variants(self, product: Product, colors: list[str], sizes: list):
        """Crea las variantes con un stock variado y realista.

        Se deja deliberadamente alguna combinación agotada para poder probar
        el comportamiento de la interfaz ante la falta de stock.
        """
        for color in colors:
            for size in sizes:
                # Las tallas extremas tienen menos stock, como en una tienda real.
                if size in (Size.XS, Size.XXL):
                    stock = random.choice([0, 0, 2, 3, 5, 8])
                else:
                    stock = random.choice([0, 4, 7, 12, 18, 25, 30])

                ProductVariant.objects.update_or_create(
                    product=product,
                    size=size,
                    color=color,
                    defaults={
                        'color_hex': COLORS[color],
                        'stock': stock,
                        # El stock reservado se recalcula con las órdenes reales.
                        'reserved': 0,
                        'is_active': True,
                    },
                )
