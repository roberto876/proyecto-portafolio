# Tienda online de ropa deportiva

E-commerce completo construido con **Django 5.2**, **PostgreSQL (Supabase)** y
**Transbank Webpay Plus**, listo para desplegarse en **Vercel**. Arquitectura
monolítica, frontend en HTML, CSS y JavaScript vanilla, sin frameworks de frontend.

> ## 👉 ¿No eres programador?
> Lee **[GUIA.md](GUIA.md)**: explica paso a paso cómo verla en tu computador,
> publicarla en internet, vender de verdad y operar el panel día a día.
> Este README es la documentación técnica.

---

## Arranque rápido (desarrollo)

Sin base de datos externa ni credenciales: usa SQLite y las credenciales
públicas de integración de Transbank.

```bash
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py seed_data
venv\Scripts\python.exe manage.py runserver
```

En macOS/Linux reemplaza `venv\Scripts\python.exe` por `venv/bin/python`.
Se invoca el intérprete del entorno directamente, sin `activate`, para evitar
la política de ejecución de scripts de PowerShell.

Tienda: <http://127.0.0.1:8000/> · Panel: <http://127.0.0.1:8000/admin/>
(crea el usuario con `manage.py createsuperuser`).

## Comandos del proyecto

| Comando | Qué hace |
|---|---|
| `manage.py seed_data [--flush] [--if-empty]` | Catálogo demo: 7 categorías, 28 productos, 333 variantes. `--if-empty` no toca un catálogo existente. |
| `manage.py preparar_produccion` | Asistente interactivo: valida la URL de Supabase, migra, crea el superusuario, carga la demo y genera `vercel-env.txt` con las variables para Vercel. Idempotente. |
| `manage.py mantenimiento_tienda` | Libera reservas de órdenes abandonadas y reconcilia pagos atascados. Lo mismo que ejecuta el cron diario. |
| `manage.py test` | Suite completa (553 pruebas). |
| `manage.py check --deploy` | Revisión de seguridad para producción. |

---

## Arquitectura

```
├── config/
│   ├── settings/          base · development · testing · production (vía DJANGO_ENV)
│   ├── middleware.py      CSP, Permissions-Policy y cookie CSRF garantizada
│   └── urls.py
├── store/                 Catálogo
│   ├── models.py          Category, Product, ProductImage, ProductVariant, StoreSettings (singleton)
│   ├── services.py        Filtrado, orden y búsqueda
│   ├── storage.py         Subida a Supabase Storage (validación por firma de bytes)
│   ├── variants.py        Creación de variantes talla×color en bloque
│   └── management/commands/  seed_data · preparar_produccion
├── cart/cart.py           Carrito en sesión; precios siempre desde la BD
├── orders/
│   ├── services.py        Órdenes e inventario: reserva, liberación, descuento (atómico e idempotente)
│   ├── access.py          Enlaces firmados de acceso a una orden
│   ├── emails.py          Confirmación al cliente y aviso de venta a la tienda
│   └── regions.py         16 regiones y comunas de Chile
├── payments/
│   ├── transbank.py       Adaptador del SDK oficial (transbank-sdk 6.1)
│   └── services.py        Orquestación, idempotencia y reconciliación
├── ops/                   Salud, cron de Vercel y panel «Estado de la tienda»
├── accounts/              Registro, login, perfil, recuperación de contraseña
├── templates/  static/    HTML, CSS y JS vanilla (sin dependencias de terceros)
└── tests_integration.py   Recorridos completos de compra
```

La lógica de negocio vive en `services.py`; las vistas solo orquestan.

### Flujo de una compra

```
Carrito (sesión) → Checkout → create_order_from_cart()
   · select_for_update() sobre las variantes (orden por PK: sin interbloqueos)
   · precios y totales recalculados desde la BD
   · Order PENDING_PAYMENT + stock RESERVADO
      ↓
start_transaction() → Transbank create() → formulario de Webpay
      ↓
/pagos/retorno/  (GET o POST, según ambiente)
   · token_ws            → confirm_transaction()
                            CREATED → PROCESSING (reclamo atómico, sin bloqueo durante la red)
                            commit() → valida monto y buy_order contra la BD
                            response_code == 0 y status == AUTHORIZED ?
                              ├─ sí → PAID + stock DESCONTADO + correos (on_commit)
                              └─ no → PAYMENT_REJECTED + stock LIBERADO (reintentable)
   · TBK_TOKEN           → anulación, solo si el token coincide con la transacción
   · sin token (timeout) → expiración, solo si TBK_ID_SESION coincide
      ↓
Redirección con enlace firmado → página de éxito o de fallo
```

El retorno **no escribe en la sesión**: cuando Transbank vuelve por POST
cross-site, la cookie de sesión no viaja (SameSite=Lax) y escribir en ella
crearía una sesión nueva que reemplazaría la del cliente. El acceso a la orden
se autoriza con un enlace firmado (`django.core.signing`, 30 días).

---

## Seguridad

| Riesgo | Mitigación |
|---|---|
| Manipulación de precios o totales | Siempre se recalculan desde la BD; nada del navegador entra al cálculo. |
| Manipulación de cantidades | Tipo, rango (1–10) y stock validados en servidor. |
| Declarar un pago como exitoso desde el cliente | El estado sale solo de `commit()`/`status()` de Transbank, exigiendo `response_code == 0` **y** `AUTHORIZED`, con monto y `buy_order` verificados. |
| Doble cobro / doble descuento de stock | Reclamo atómico `CREATED → PROCESSING`; flags `stock_reserved`/`stock_committed`; restricción única en BD: un pago autorizado por orden. |
| Anular o ver órdenes ajenas vía `/pagos/retorno/` | La anulación exige `TBK_TOKEN` idéntico al token registrado; la expiración exige el `session_id` aleatorio. Datos no reconocidos → respuesta genérica. |
| Sesión del cliente reemplazada al volver de Webpay | El retorno no toca la sesión; acceso por enlace firmado. |
| Adivinar números de orden | 32 bits aleatorios por orden; 404 (no 403) ante accesos no autorizados. |
| Venta simultánea del último producto | `select_for_update()` dentro de `transaction.atomic()`. |
| Redirección abierta en login | `next` validado con `url_has_allowed_host_and_scheme`. |
| CSRF | Protección de Django en formularios y `fetch()`. El retorno de Webpay está exento (lo llama Transbank) y se valida contra la BD. |
| XSS | Autoescape; `textContent` en JS; `json_script` para datos; CSP `script-src 'self'` sin `unsafe-inline`. |
| Subidas maliciosas | Firma de bytes (JPEG/PNG/WebP), tope de 4 MB, nombre generado por el servidor. |
| Cron invocado por terceros | `Authorization: Bearer $CRON_SECRET` comparado en tiempo constante; sin secreto, cerrado. |
| Datos de tarjeta | Solo se guardan los últimos 4 dígitos; la respuesta se sanea antes de persistir. |
| Secretos | Solo por entorno; `production.py` se niega a arrancar si faltan, con instrucciones. |

**Sobre la CSP:** `script-src 'self'` es estricta (las animaciones usan CSS e
`IntersectionObserver` en vez de librerías por CDN). `style-src` admite
`'unsafe-inline'` porque colores de variante y anchos dinámicos provienen de la
BD, y los hashes/nonces de CSP no aplican a atributos `style`.

---

## Despliegue: decisiones técnicas verificadas

Detalles comprobados contra la documentación oficial (Vercel, Supabase, Django,
Transbank) que un despliegue real necesita:

- **Detección en Vercel:** sin `vercel.json` de build. Vercel encuentra
  `manage.py`, lee `WSGI_APPLICATION` y ejecuta `collectstatic` solo
  (`CompressedManifestStaticFilesStorage` está soportado). Python 3.12 vía `.python-version`.
- **Hosts:** se añaden automáticamente `VERCEL_PROJECT_PRODUCTION_URL` (dominio
  estable), `VERCEL_URL` y `VERCEL_BRANCH_URL`. Sin el primero, el dominio
  principal respondería 400.
- **Supabase:** se usa el *Transaction pooler* (6543). Las conexiones directas
  son IPv6. El pooler no admite prepared statements (Django 5.2 ya fija
  `prepare_threshold=None` con psycopg 3) ni cursores del lado del servidor
  (`DISABLE_SERVER_SIDE_CURSORS=True`). `CONN_MAX_AGE=0` en serverless.
- **Límites de Vercel:** peticiones de 4,5 MB como máximo (subidas limitadas a
  4 MB); `maxDuration` 30 s con `TRANSBANK_TIMEOUT` 20 s y `EMAIL_TIMEOUT` 10 s.
- **Cron:** diario (el plan Hobby solo permite uno al día, ±59 min). Las reservas
  vencidas además se liberan de forma oportunista al navegar, con un freno de 60 s.
- **Uso comercial:** el plan Hobby de Vercel lo prohíbe expresamente (incluye
  procesar pagos). Una tienda que cobra necesita el plan Pro.
- **Migraciones:** Vercel no las ejecuta; las aplica `preparar_produccion`
  (o `migrate` con `DATABASE_URL` de Supabase).

Variables de entorno: ver [.env.example](.env.example) (todas documentadas).

---

## Pruebas

**553 pruebas**, ejecutadas contra SQLite y contra **PostgreSQL 16 real**.
Ninguna contacta la API de Transbank: se usa un doble de prueba con el mismo contrato.

```bash
venv\Scripts\python.exe manage.py test
```

Para correrlas contra PostgreSQL (recomendado antes de desplegar):

```bash
set TEST_DATABASE_URL=postgresql://usuario:clave@localhost:5432/postgres
venv\Scripts\python.exe manage.py test
```

Cobertura por área: catálogo, filtros y SEO; carrito y cálculo de envío;
órdenes, inventario y concurrencia; pagos (aprobado, rechazado, anulado,
expirado, error de red, doble confirmación, montos alterados, retornos
forjados); correos; enlaces firmados; mantenimiento y cron; asistente de
despliegue (de extremo a extremo); panel de administración (subidas, variantes,
CSV); cuentas (hashing, redirección abierta, recuperación); cabeceras de seguridad.

---

## Limitaciones conocidas

- **Reembolsos:** se hacen en el portal de Transbank; el panel solo registra el estado.
- **Boletas:** la tienda no emite documentos tributarios (SII).
- **Textos legales:** son una base general; deben adaptarse a cada negocio.
- **Login sin límite de intentos:** no hay throttling de autenticación. Para
  operación comercial conviene añadirlo (p. ej. `django-axes`) o un WAF.
- **Imágenes demo:** el catálogo de ejemplo usa fotos de Unsplash por enlace.
- **Supabase gratis** puede pausar proyectos inactivos; para producción, plan Pro.

Las fotografías de demostración provienen de [Unsplash](https://unsplash.com).
"# proyecto-portafolio" 
