# 📘 Guía de la tienda — léela primero

Esta guía explica, paso a paso y sin tecnicismos, cómo:

1. **[Ver la tienda en tu computador](#parte-1--ver-la-tienda-en-tu-computador-15-minutos)** (para mostrarla o probarla).
2. **[Publicarla en internet](#parte-2--publicarla-en-internet-30-minutos)** con Supabase y Vercel.
3. **[Usarla para vender de verdad](#parte-3--vender-de-verdad)** (lo que exige la ley y los bancos).
4. **[Operarla día a día](#parte-4--el-día-a-día-manual-del-panel)**: productos, pedidos, stock.

Si algo falla, ve directo a **[Problemas frecuentes](#-problemas-frecuentes)**.

> 💡 **Cómo leer los bloques grises:** son comandos. Cópialos **exactamente**
> (hay un botón de copiar al pasar el mouse) y pégalos en la terminal con
> clic derecho. Luego presiona **Enter**.

---

## Parte 1 — Ver la tienda en tu computador (15 minutos)

No necesitas cuentas ni internet especial: la tienda trae todo para funcionar
sola, con productos de ejemplo y pagos de prueba.

### 1.1 Instalar Python (solo la primera vez)

1. Entra a **<https://www.python.org/downloads/>** y descarga la versión más reciente.
2. Abre el instalador y, **antes de hacer clic en Install**, marca la casilla
   **«Add python.exe to PATH»** (abajo del todo). Esto es lo más importante.
3. Haz clic en **Install Now** y espera a que termine.

### 1.2 Abrir una terminal en la carpeta de la tienda

1. Abre la carpeta del proyecto en el Explorador de archivos (la que contiene
   el archivo `manage.py`).
2. Haz clic en la **barra de dirección** de arriba, borra lo que dice, escribe
   `powershell` y presiona **Enter**. Se abre una ventana azul o negra: esa es
   la terminal, ya ubicada en la carpeta correcta.

### 1.3 Instalar y encender la tienda

Pega este bloque completo en la terminal y presiona **Enter**. La primera vez
tarda unos minutos (descarga lo necesario):

```bash
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py seed_data
venv\Scripts\python.exe manage.py runserver
```

Cuando veas un mensaje como `Starting development server at http://127.0.0.1:8000/`,
la tienda está funcionando.

> 🍎 **¿Usas Mac?** Usa `python3 -m venv venv` en la primera línea y cambia
> `venv\Scripts\python.exe` por `venv/bin/python` en las demás.

### 1.4 Abrirla en el navegador

Abre **<http://127.0.0.1:8000/>** en Chrome, Edge o Firefox. Verás la tienda con
28 productos de ejemplo. Mientras la terminal siga abierta, la tienda sigue encendida.

### 1.5 Crear tu usuario de administrador

Para entrar al panel donde se gestionan productos y pedidos:

1. Abre **otra** terminal en la misma carpeta (repite el paso 1.2).
2. Pega esto y responde las preguntas (usuario, email y contraseña; la contraseña
   no se ve mientras escribes, es normal):

```bash
venv\Scripts\python.exe manage.py createsuperuser
```

3. Entra a **<http://127.0.0.1:8000/admin/>** con ese usuario.

### 1.6 Probar una compra (sin dinero real)

Mientras no se configure lo contrario, **los pagos son simulados**: verás un
aviso amarillo arriba que lo recuerda.

1. Abre un producto, elige **color** y **talla**, y pulsa **Agregar al carrito**.
2. Ve al carrito → **Finalizar compra** → completa tus datos → **Pagar**.
3. Llegarás al formulario de Webpay. Usa esta tarjeta de prueba de Transbank:
   - **Número:** `4051 8856 0044 6623`
   - **CVV:** `123` · **Vencimiento:** cualquier fecha futura
4. Cuando pida RUT y clave, usa **RUT** `11.111.111-1` y **clave** `123`.
5. Acepta el pago. Volverás a la tienda con la compra confirmada.

Para probar un pago **rechazado**, usa la tarjeta `5186 0595 5959 0568`.

> Estas tarjetas son públicas y oficiales de Transbank, y solo funcionan en modo prueba.

### 1.7 Apagar y volver a encender

- **Apagar:** en la terminal donde corre la tienda, presiona `Ctrl` + `C`.
- **Encender otro día:** abre la terminal en la carpeta (paso 1.2) y pega solo:

```bash
venv\Scripts\python.exe manage.py runserver
```

---

## Parte 2 — Publicarla en internet (30 minutos)

Vas a usar tres servicios, todos con plan gratuito para empezar:

| Servicio | Para qué sirve |
|---|---|
| **GitHub** | Guarda el código de la tienda. |
| **Supabase** | Guarda los datos: productos, pedidos, clientes. |
| **Vercel** | Publica la tienda en internet y la mantiene encendida. |

> ⚠️ **El plan gratuito de Vercel no permite uso comercial.** Sirve para la
> demostración (pagos simulados). Para vender de verdad necesitas el plan Pro
> de Vercel: ver la [Parte 3](#parte-3--vender-de-verdad).

### Paso 1 — Crear las cuentas

1. **GitHub:** <https://github.com/signup>
2. **Supabase:** <https://supabase.com/dashboard/sign-up> → elige **«Continue with GitHub»**.
3. **Vercel:** <https://vercel.com/signup> → elige **«Continue with GitHub»**.

Usar GitHub para entrar a Supabase y Vercel evita tener más contraseñas y
conecta todo automáticamente.

### Paso 2 — Subir la tienda a GitHub (con GitHub Desktop)

1. Descarga e instala **GitHub Desktop**: <https://desktop.github.com/> e inicia sesión con tu cuenta.
2. Menú **File → Add local repository…** y elige la carpeta de la tienda.
3. Aparecerá un aviso de que la carpeta no es un repositorio: haz clic en
   **«create a repository»** y luego en **Create repository**.
4. Arriba, haz clic en **Publish repository**. Deja marcada la opción
   **«Keep this code private»** y confirma.

Listo: tu código está en GitHub. Los archivos con claves secretas **no se suben**,
porque la tienda ya los tiene excluidos.

### Paso 3 — Crear la base de datos en Supabase

1. En Supabase, haz clic en **New project**.
2. Completa:
   - **Name:** el nombre de tu tienda.
   - **Database Password:** haz clic en **Generate a password** y **cópiala en un lugar seguro**. La necesitarás enseguida.
   - **Region:** elige **South America (São Paulo)**, la más cercana a Chile.
3. Haz clic en **Create new project** y espera 1 o 2 minutos a que termine.
4. Arriba en la página del proyecto, haz clic en el botón **Connect**.
5. En la ventana que se abre, busca la opción **«Transaction pooler»** y copia
   la dirección que empieza con `postgresql://` y termina en `:6543/postgres`.

> ❗ Esa dirección trae el texto `[YOUR-PASSWORD]`. **Todavía no lo cambies**:
> el asistente del paso 4 te avisará si lo olvidas.

### Paso 4 — Preparar Supabase con el asistente

Esto crea las tablas, tu usuario administrador y las claves secretas. En la
terminal, dentro de la carpeta de la tienda (paso 1.2 de la Parte 1), pega:

```bash
venv\Scripts\python.exe manage.py preparar_produccion
```

El asistente te pedirá:

1. **La dirección de Supabase:** pégala y **reemplaza** `[YOUR-PASSWORD]`
   (incluidos los corchetes) por la contraseña que guardaste en el paso 3.
2. **Un usuario, tu email y una contraseña** para entrar al panel de la tienda online.
3. **Si quieres productos de ejemplo** (responde `s` para la demostración).

Al terminar dirá **«¡Todo listo en Supabase!»** y habrá creado el archivo
**`vercel-env.txt`** en la carpeta de la tienda.

> Si el asistente muestra un error, dice exactamente qué corregir. Los más
> comunes están en [Problemas frecuentes](#-problemas-frecuentes).

### Paso 5 — Publicar en Vercel

1. En Vercel, haz clic en **Add New… → Project**.
2. En la lista de repositorios de GitHub, busca el de tu tienda y haz clic en **Import**.
3. En la pantalla **Configure Project**, **no toques nada todavía** y abre la
   sección **Environment Variables**.
4. Abre el archivo **`vercel-env.txt`** con el Bloc de notas, selecciona todo
   (`Ctrl` + `A`), cópialo (`Ctrl` + `C`) y pégalo (`Ctrl` + `V`) en la primera
   casilla **Key**. Vercel separa las variables solo: verás 5 filas llenas.
5. Ahora sí, haz clic en **Deploy** y espera 2 o 3 minutos.
6. Cuando aparezca **«Congratulations!»**, haz clic en la imagen de la tienda
   para abrirla. Tu dirección es del tipo `https://tu-tienda.vercel.app`.

> 🔒 **Borra `vercel-env.txt`** cuando termines: contiene tus claves secretas.
> Si algún día lo necesitas de nuevo, vuelve a ejecutar el asistente.

### Paso 6 — Comprobar que todo funciona

1. Entra a `https://tu-tienda.vercel.app/admin/` con el usuario que creaste en el paso 4.
2. En la parte de arriba, haz clic en **🩺 Estado de la tienda**.
3. Verás un semáforo con cada parte de la tienda. **Verde** está bien; **naranja**
   indica algo por completar, con la instrucción de qué hacer; **rojo** es un problema.

En la demostración es normal ver en naranja «Pagos en modo PRUEBA», «Correos»
y «Datos legales». Para vender de verdad hay que dejarlos en verde (Parte 3).

### Paso 7 (opcional) — Subir fotos desde el panel

Sin este paso, en el panel debes pegar enlaces de imágenes. Con él, puedes subir
fotos directamente desde tu computador.

1. En Supabase, menú izquierdo **Storage → New bucket**.
2. Nombre: `productos` (exactamente así). Activa **Public bucket**. Guarda.
3. En **Project Settings → API Keys**, copia una **clave secreta** (en la
   pestaña de claves nuevas empieza con `sb_secret_`; en la pestaña *Legacy* se
   llama `service_role`). **Nunca uses la clave `anon` o `publishable`.**
4. En **Project Settings → Data API**, copia la **Project URL** (del tipo `https://abcd.supabase.co`).
5. En Vercel: tu proyecto → **Settings → Environment Variables**. Agrega:
   - `SUPABASE_URL` = la Project URL
   - `SUPABASE_SERVICE_ROLE_KEY` = la clave secreta
6. Ve a **Deployments**, en el último despliegue haz clic en **⋯ → Redeploy**.

### Paso 8 (recomendado) — Activar los correos

Sin esto, los clientes no reciben la confirmación de compra, tú no recibes
avisos de ventas y no funciona «Olvidé mi contraseña». Con una cuenta de Gmail:

1. Activa la **verificación en 2 pasos** de tu cuenta Google.
2. Entra a <https://myaccount.google.com/apppasswords>, crea una
   **contraseña de aplicación** llamada «Tienda» y copia las 16 letras.
3. En Vercel → **Settings → Environment Variables**, agrega:

   | Key | Value |
   |---|---|
   | `EMAIL_HOST` | `smtp.gmail.com` |
   | `EMAIL_PORT` | `587` |
   | `EMAIL_HOST_USER` | tu correo de Gmail |
   | `EMAIL_HOST_PASSWORD` | las 16 letras de la contraseña de aplicación |
   | `DEFAULT_FROM_EMAIL` | `Tu Tienda <tucorreo@gmail.com>` |

4. **Deployments → ⋯ → Redeploy.**
5. En el panel de la tienda, entra a **Ajustes de la tienda** y completa
   **Email de la tienda**: ahí llegarán los avisos de cada venta.

### Paso 9 (opcional) — Tu propio dominio (ej. `mitienda.cl`)

1. Compra el dominio (los `.cl` se compran en <https://www.nic.cl/>).
2. En Vercel → **Settings → Domains → Add**, escribe tu dominio y sigue las
   instrucciones para configurar el DNS donde lo compraste.
3. Agrega en Vercel la variable `ALLOWED_HOSTS` con tu dominio (ej.
   `mitienda.cl,www.mitienda.cl`) y haz **Redeploy**.

### ¿Cómo actualizo la tienda publicada?

Si alguien cambia el código: en GitHub Desktop escribe un resumen abajo a la
izquierda, haz clic en **Commit to main** y luego en **Push origin**. Vercel
publica la nueva versión solo, en 2 o 3 minutos. Si el cambio incluye nuevas
tablas, vuelve a ejecutar el asistente del paso 4 (es seguro repetirlo).

---

## Parte 3 — Vender de verdad

La tienda está técnicamente lista para cobrar. Lo que falta son **trámites**.
Esta es la lista completa, en orden:

### ✅ 1. Formalizar el negocio

- **Inicio de actividades en el SII** (<https://www.sii.cl/>), como persona
  natural o empresa.
- **Boletas:** la tienda **no emite boletas ni facturas**. Por cada venta debes
  emitirlas tú. El SII ofrece un sistema gratuito de boleta electrónica.

### ✅ 2. Completar los datos legales de la tienda

La Ley del Consumidor exige que quien vende online muestre su identidad.
En el panel → **Ajustes de la tienda** → **Datos legales**, completa:
razón social (o tu nombre), RUT y dirección comercial. Aparecen automáticamente
en el pie de página de la tienda.

Revisa también los textos de **Términos y condiciones**, **Privacidad** y
**Envíos y devoluciones** (enlaces al pie de la tienda). Son una base general:
conviene que alguien con conocimiento legal los ajuste a tu negocio. Recuerda
que la ley chilena da al comprador online **derecho a retracto**.

### ✅ 3. Contratar Webpay Plus y validar la integración

Transbank no deja cobrar sin estos pasos:

1. **Afiliarte:** completa el formulario en <https://publico.transbank.cl/> y
   fírmalo. Te enviarán por correo tu **código de comercio**.
2. **Validar la tienda:** Transbank exige demostrar que la integración funciona.
   Con la tienda en modo prueba, haz compras de prueba: al menos una **aprobada**,
   una **rechazada** (tarjeta de rechazo) y una **anulada** (pulsa «Anular» en
   Webpay). Para cada una, anota el **número de orden, la fecha y la hora**:
   los encuentras en el panel → **Pagos → Transacciones de pago**.
3. Envía esas evidencias en el **formulario de validación de Transbank Developers**,
   junto con el **logo de la tienda en PNG de 130 × 59 píxeles**.
4. Cuando Transbank apruebe, te enviará por correo la **llave secreta (API Key)**.
5. En Vercel → **Settings → Environment Variables**, cambia o agrega:

   | Key | Value |
   |---|---|
   | `TRANSBANK_ENVIRONMENT` | `production` |
   | `TRANSBANK_COMMERCE_CODE` | tu código de comercio |
   | `TRANSBANK_API_KEY` | la llave secreta que te enviaron |

6. **Deployments → ⋯ → Redeploy.** El aviso amarillo de «modo demostración»
   desaparece y **Estado de la tienda** muestra «Pagos» en verde.
7. Transbank pide hacer **una compra real de $50** para confirmar. Hazla tú
   mismo. Si quieres, luego anúlala desde el portal de Transbank.

### ✅ 4. Cambiar a planes comerciales

| Servicio | Qué hacer y por qué |
|---|---|
| **Vercel** | Pasa al plan **Pro**: el gratuito prohíbe expresamente procesar pagos. |
| **Supabase** | Muy recomendable el plan **Pro**: los proyectos gratuitos pueden pausarse tras una semana sin uso y tienen respaldos limitados. Una tienda pausada no vende. |
| **Transbank** | Cobra una comisión por cada venta, según tu contrato. |

### ✅ 5. Poner tu catálogo real

1. En el panel → **Tienda → Productos**, selecciona los productos de ejemplo,
   elige la acción **«Desactivar (ocultar de la tienda)»** o elimínalos.
2. Crea tus productos con **tus propias fotos** (ver Parte 4). Las imágenes de
   ejemplo son de un banco de fotos público y no representan tus productos.

### ✅ 6. Revisar el Estado de la tienda

En el panel → **🩺 Estado de la tienda**, todo debería estar en verde antes de
anunciar la tienda.

---

## Parte 4 — El día a día (manual del panel)

Entra a **`tu-tienda.vercel.app/admin/`**. En la parte de arriba tienes accesos
rápidos a lo más usado.

### Ajustes de la tienda

Nombre, eslogan, datos legales, email, teléfono, WhatsApp, redes sociales y
**costos de despacho**. Todo se aplica de inmediato, sin tocar código.

- **WhatsApp:** escribe el número con código de país, solo números
  (ej. `56912345678`). Aparece un botón verde flotante en la tienda.
- **Envío gratis desde:** pon `0` si no quieres ofrecer envío gratis.
- **Costo de despacho:** pon `0` si el despacho siempre es gratis.

### Crear un producto

1. **Tienda → Productos → Añadir producto.**
2. Completa nombre, categoría, género, descripción y **precio**.
   Para una **oferta**, pon el precio anterior (más alto) en **Precio anterior**:
   la tienda muestra el descuento sola.
3. **Foto principal:** sube un archivo o pega el enlace de una imagen.
4. **Crear variantes rápido:** marca las **tallas**, escribe los **colores**
   separados por coma (ej. `Negro, Blanco, Azul marino`) y el **stock inicial**.
   Al guardar se crean todas las combinaciones de una vez.
5. Marca **Activo** para mostrarlo en la tienda y **Destacado** para ponerlo en la portada.
6. **Guardar.**

Luego puedes ajustar el stock de cada combinación en la tabla de variantes del
mismo producto, y el color de la muestra con el selector de color.

### Controlar el stock

**Tienda → Variantes** muestra todo el inventario. Puedes cambiar el stock
directamente en la lista y pulsar **Guardar**. Usa el filtro de la derecha
**«nivel de stock → Stock bajo»** para ver qué reponer.

- **Stock físico:** las unidades que tienes.
- **Reservado:** unidades de pedidos que se están pagando. Lo maneja la tienda
  sola; si un cliente abandona el pago, se libera automáticamente en 30 minutos.
- **Disponible:** lo que se puede vender (físico − reservado).

### Gestionar pedidos

**Órdenes → Órdenes** (o el acceso rápido **📦 Pedidos por despachar**).

Ciclo de un pedido:

```
Pendiente de pago → Pagada → En preparación → Enviada → Entregada
```

1. Cuando llega una venta, el pedido aparece como **Pagada** (y te llega un
   correo, si activaste los correos).
2. Ábrelo para ver los productos y la dirección de despacho.
3. Para avanzar el estado, marca los pedidos en la lista, elige la acción
   (**Marcar como en preparación / enviada / entregada**) y pulsa **Ir**.
   El cliente ve el estado actualizado en su cuenta.

Otras acciones útiles:

- **Exportar a Excel (CSV):** marca los pedidos y elige esa acción. Se descarga
  un archivo que se abre con doble clic en Excel.
- **Cancelar y liberar stock:** para pedidos no pagados.

### Devolver dinero (reembolsos)

Los reembolsos se hacen en el **portal de Transbank** (no desde la tienda).
Una vez hecho, abre la orden en el panel y cambia su **Estado** a
**Reembolsada**. Si el producto vuelve a tu bodega, súmalo al stock en
**Tienda → Variantes**.

### Ver pagos

**Pagos → Transacciones de pago** muestra cada intento de pago con su resultado.
Es solo de consulta: por seguridad no se puede modificar. Aquí encuentras los
números de orden, fechas y horas que pide Transbank para la validación.

---

## 🛟 Problemas frecuentes

**«python no se reconoce como un comando» o se abre la Microsoft Store**
: Python no quedó instalado con la opción *Add to PATH*. Desinstálalo, vuelve a
instalarlo desde python.org marcando **«Add python.exe to PATH»** y abre una
terminal nueva.

**El asistente dice «La contraseña de la base de datos no es correcta»**
: En Supabase → **Project Settings → Database → Reset database password**.
Genera una nueva, cópiala y vuelve a ejecutar el asistente.

**El asistente dice «Esa es la conexión directa…»**
: Copiaste la dirección equivocada. En Supabase → **Connect** → elige
**Transaction pooler** (la que termina en `:6543/postgres`).

**El asistente dice «Supabase no responde»**
: Revisa tu internet. Si el proyecto estaba en pausa, en Supabase aparece un
botón **Restore project**: úsalo y espera un par de minutos.

**En Vercel el despliegue falla con «FALTA SECRET_KEY» o «FALTA DATABASE_URL»**
: No se pegaron las variables. Ve a **Settings → Environment Variables**, pega
el contenido de `vercel-env.txt` (o vuelve a generarlo con el asistente) y haz
**Deployments → ⋯ → Redeploy**.

**La página dice «Bad Request (400)»**
: Estás entrando por un dominio propio que la tienda no conoce. Agrega la
variable `ALLOWED_HOSTS` con tu dominio (Parte 2, paso 9) y haz **Redeploy**.

**«Server Error (500)» o la tienda no carga**
: Entra a `/admin/estado/` (si carga) para ver qué está en rojo. Si nada carga,
en Vercel → **Deployments** → último despliegue → **Logs**: el mensaje en rojo
suele decir qué falta.

**No llegan los correos**
: Revisa **Estado de la tienda → Correos**. Si está en naranja, sigue la Parte 2,
paso 8. Revisa también la carpeta de spam.

**Al subir una foto dice que no existe el bucket o rechaza la clave**
: El mensaje dice qué corregir. Revisa que el bucket se llame exactamente
`productos`, que sea **público**, y que usaste la clave **secreta**, no la `anon`.

**Un cliente dice que pagó pero su pedido no aparece como pagado**
: Revisa en **Pagos → Transacciones de pago**. Si la transacción figura
«En confirmación», la tienda la resuelve sola en la tarea diaria consultando a
Transbank. También puedes verificarla en el portal de Transbank.

**Un producto aparece agotado pero tengo stock**
: Mira la columna **Reservado** en **Tienda → Variantes**: son unidades de un
pago en curso. Si nadie completa el pago, se liberan solas en 30 minutos.

---

*¿Eres programador o quieres entender cómo está construida? Lee el
[README.md](README.md).*
