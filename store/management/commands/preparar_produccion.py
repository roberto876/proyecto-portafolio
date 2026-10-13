"""Asistente que deja la tienda lista para publicarse en Vercel + Supabase.

Uso (una sola vez, desde tu computador, dentro de la carpeta del proyecto)::

    python manage.py preparar_produccion

El asistente pregunta lo mínimo y hace todo lo demás:

1. Pide la dirección de la base de datos de Supabase y la valida.
2. Crea todas las tablas en Supabase (migraciones).
3. Crea tu usuario administrador.
4. Opcionalmente carga el catálogo de demostración.
5. Genera las claves secretas y escribe ``vercel-env.txt`` con el bloque de
   variables listo para pegar en Vercel.

Es seguro ejecutarlo varias veces: no duplica datos ni borra nada.
"""
import getpass
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.management.utils import get_random_secret_key

#: Archivo generado con las variables para Vercel. Está en .gitignore.
OUTPUT_FILENAME = 'vercel-env.txt'

#: Traducción de errores frecuentes de conexión a instrucciones concretas.
CONNECTION_HINTS = (
    ('password authentication failed',
     'La contraseña de la base de datos no es correcta. En Supabase: Project '
     'Settings > Database > Reset database password, y vuelve a copiar la dirección.'),
    ('could not translate host name',
     'No se encontró el servidor. Revisa que copiaste la dirección completa, sin espacios.'),
    ('Name or service not known',
     'No se encontró el servidor. Revisa que copiaste la dirección completa, sin espacios.'),
    ('timeout',
     'Supabase no responde. Revisa tu internet y que el proyecto no esté en pausa '
     '(en el panel de Supabase aparece un botón «Restore» si lo está).'),
    ('Tenant or user not found',
     'El usuario de la dirección no es válido. Copia de nuevo la cadena «Transaction pooler».'),
    ('Network is unreachable',
     'Tu red no puede llegar a esa dirección. Usa la cadena «Transaction pooler» (puerto 6543).'),
)


class Command(BaseCommand):
    help = 'Asistente: prepara Supabase y genera las variables para Vercel.'

    def add_arguments(self, parser):
        parser.add_argument('--database-url', help='Dirección de Supabase (si no, se pregunta).')
        parser.add_argument('--admin-username', help='Usuario administrador a crear.')
        parser.add_argument('--admin-email', help='Email del administrador.')
        parser.add_argument(
            '--demo', choices=('si', 'no'),
            help='Cargar el catálogo de demostración (si no, se pregunta).',
        )
        parser.add_argument(
            '--no-input', action='store_true',
            help='No hacer preguntas. La contraseña del admin se lee de la '
                 'variable DJANGO_SUPERUSER_PASSWORD.',
        )
        parser.add_argument(
            '--output', default=str(Path(settings.BASE_DIR) / OUTPUT_FILENAME),
            help='Dónde escribir el bloque de variables para Vercel.',
        )
        # Solo para pruebas automatizadas: permite una base SQLite local.
        parser.add_argument('--allow-sqlite', action='store_true', help='(uso interno)')

    # -- Flujo principal -------------------------------------------------------
    def handle(self, *args, **options):
        self.interactive = not options['no_input']
        self.allow_sqlite = options['allow_sqlite']

        self._title('Asistente de publicación de la tienda')
        self.stdout.write(
            'Te voy a pedir 3 cosas: la dirección de tu base de datos de Supabase,\n'
            'un usuario y una contraseña para entrar al panel de administración.\n'
        )

        database_url = self._ask_database_url(options['database_url'])

        self._step(1, 'Creando las tablas en Supabase (puede tardar un minuto)...')
        self._run_manage(['migrate', '--noinput'], database_url)
        self._ok('Base de datos lista.')

        self._step(2, 'Usuario administrador')
        self._create_admin(database_url, options['admin_username'], options['admin_email'])

        self._step(3, 'Catálogo de demostración')
        if self._wants_demo(options['demo']):
            self._run_manage(['seed_data', '--if-empty'], database_url)
            self._ok('Catálogo de demostración cargado (si ya había productos, no se tocaron).')
        else:
            self.stdout.write('  Omitido. Podrás crear tus productos desde el panel.')

        self._step(4, 'Generando las claves y el archivo para Vercel')
        output = Path(options['output'])
        self._write_vercel_env(output, database_url)
        self._ok(f'Listo: {output}')

        self._next_steps(output)

    # -- Base de datos ---------------------------------------------------------
    def _ask_database_url(self, provided: str | None) -> str:
        """Pide y valida la dirección hasta que sea correcta."""
        url = (provided or '').strip()
        while True:
            if not url:
                if not self.interactive:
                    raise CommandError('Falta --database-url.')
                self.stdout.write(
                    '\nPega la dirección de Supabase (Connect > Transaction pooler).\n'
                    'Empieza con postgresql:// y termina en :6543/postgres'
                )
                url = input('> ').strip()

            problem = self.validate_database_url(url, allow_sqlite=self.allow_sqlite)
            if problem is None:
                return url
            if not self.interactive:
                raise CommandError(problem)
            self.stderr.write(self.style.ERROR(f'\n  {problem}\n'))
            url = ''

    @staticmethod
    def validate_database_url(url: str, *, allow_sqlite: bool = False) -> str | None:
        """Devuelve un mensaje de error en lenguaje llano, o ``None`` si es válida."""
        if allow_sqlite and url.startswith('sqlite:///'):
            return None
        if not url.startswith(('postgresql://', 'postgres://')):
            return ('La dirección debe empezar con postgresql://. Cópiala desde '
                    'Supabase: botón Connect, pestaña «Connection string».')
        if '[YOUR-PASSWORD]' in url or 'TU_PASSWORD' in url:
            return ('Todavía dice [YOUR-PASSWORD]. Reemplaza ese texto (con los '
                    'corchetes) por la contraseña de tu base de datos.')

        import dj_database_url
        try:
            dj_database_url.parse(url)
        except ValueError:
            return ('La dirección no es válida. Si tu contraseña tiene símbolos '
                    'como @ # / ? o %, cámbiala en Supabase por una con solo '
                    'letras y números y vuelve a copiar la dirección.')

        parsed = urlparse(url)
        if not parsed.hostname or not parsed.password:
            return 'A la dirección le falta el servidor o la contraseña. Cópiala completa.'
        if parsed.hostname.startswith('db.') and parsed.hostname.endswith('.supabase.co'):
            return ('Esa es la conexión directa, que no funciona desde Vercel. '
                    'En Supabase elige «Transaction pooler» (puerto 6543) y copia esa.')
        if parsed.port not in (6543, 5432):
            return 'El puerto debería ser 6543 (Transaction pooler).'
        return None

    def _run_manage(self, arguments: list[str], database_url: str) -> None:
        """Ejecuta un comando de Django contra la base indicada."""
        env = {
            **os.environ,
            'DJANGO_ENV': 'development',
            'DATABASE_URL': database_url,
        }
        result = subprocess.run(
            [sys.executable, 'manage.py', *arguments],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise CommandError(self._explain_failure(result.stderr or result.stdout))

    @staticmethod
    def _explain_failure(output: str) -> str:
        """Convierte un error técnico en una instrucción comprensible."""
        for needle, hint in CONNECTION_HINTS:
            if needle.lower() in output.lower():
                return hint
        last_line = next(
            (line for line in reversed(output.strip().splitlines()) if line.strip()),
            'error desconocido',
        )
        return f'Algo falló: {last_line}\nRevisa GUIA.md, sección «Problemas frecuentes».'

    # -- Administrador ---------------------------------------------------------
    def _create_admin(self, database_url, username, email) -> None:
        username = (username or '').strip() or self._ask('Nombre de usuario', default='admin')
        email = (email or '').strip() or self._ask('Tu email')
        password = self._ask_password()

        env_password = {'DJANGO_SUPERUSER_PASSWORD': password}
        env = {
            **os.environ,
            **env_password,
            'DJANGO_ENV': 'development',
            'DATABASE_URL': database_url,
            'DJANGO_SUPERUSER_USERNAME': username,
            'DJANGO_SUPERUSER_EMAIL': email,
        }
        result = subprocess.run(
            [sys.executable, 'manage.py', 'createsuperuser', '--noinput'],
            cwd=settings.BASE_DIR, env=env, capture_output=True, text=True,
        )
        output = (result.stderr or '') + (result.stdout or '')
        if result.returncode == 0:
            self._ok(f'Administrador «{username}» creado.')
        elif 'already taken' in output or 'ya existe' in output.lower():
            self.stdout.write(f'  El usuario «{username}» ya existía: se mantiene su contraseña.')
        else:
            raise CommandError(self._explain_failure(output))

    def _ask_password(self) -> str:
        """Pide una contraseña robusta. Nunca la imprime ni la guarda."""
        if not self.interactive:
            password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
            if not password:
                raise CommandError('Define DJANGO_SUPERUSER_PASSWORD para el modo sin preguntas.')
            self._check_password(password)
            return password

        while True:
            password = getpass.getpass('  Contraseña (no se ve al escribir): ')
            confirm = getpass.getpass('  Repite la contraseña: ')
            if password != confirm:
                self.stderr.write(self.style.ERROR('  No coinciden. Inténtalo de nuevo.'))
                continue
            try:
                self._check_password(password)
            except CommandError as exc:
                self.stderr.write(self.style.ERROR(f'  {exc}'))
                continue
            return password

    @staticmethod
    def _check_password(password: str) -> None:
        # `createsuperuser --noinput` no valida la contraseña: se hace aquí.
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages)) from exc

    # -- Demo y salida ---------------------------------------------------------
    def _wants_demo(self, choice: str | None) -> bool:
        if choice:
            return choice == 'si'
        if not self.interactive:
            return False
        answer = self._ask('¿Cargar productos de ejemplo para mostrar la tienda? (s/n)', default='s')
        return answer.lower().startswith('s')

    @staticmethod
    def build_vercel_env(database_url: str) -> str:
        """Bloque de variables para pegar en Vercel (formato .env)."""
        values = {
            'DJANGO_ENV': 'production',
            'SECRET_KEY': get_random_secret_key(),
            'DATABASE_URL': database_url,
            'CRON_SECRET': secrets.token_urlsafe(32),
            'TRANSBANK_ENVIRONMENT': 'integration',
        }
        return ''.join(f'{key}={value}\n' for key, value in values.items())

    def _write_vercel_env(self, output: Path, database_url: str) -> None:
        output.write_text(self.build_vercel_env(database_url), encoding='utf-8')

    def _next_steps(self, output: Path) -> None:
        self._title('¡Todo listo en Supabase!')
        self.stdout.write(
            'Ahora, en Vercel:\n'
            '  1. Importa tu repositorio de GitHub (botón «Add New… > Project»).\n'
            '  2. ANTES de pulsar «Deploy», abre «Environment Variables».\n'
            f'  3. Abre el archivo {output.name} con el Bloc de notas, copia TODO\n'
            '     su contenido y pégalo en la primera casilla «Key».\n'
            '     Vercel separa las variables solo.\n'
            '  4. Pulsa «Deploy».\n\n'
        )
        self.stdout.write(self.style.WARNING(
            f'IMPORTANTE: {output.name} contiene tus claves secretas. Cuando las\n'
            'hayas pegado en Vercel, bórralo. Nunca lo subas a GitHub\n'
            '(ya está excluido en .gitignore).\n'
        ))

    # -- Utilidades de consola -------------------------------------------------
    def _ask(self, question: str, default: str = '') -> str:
        if not self.interactive:
            if default:
                return default
            raise CommandError(f'Falta un dato obligatorio: {question}')
        suffix = f' [{default}]' if default else ''
        while True:
            answer = input(f'  {question}{suffix}: ').strip() or default
            if answer:
                return answer

    def _title(self, text: str) -> None:
        line = '=' * 64
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{line}\n  {text}\n{line}'))

    def _step(self, number: int, text: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f'\nPaso {number}. {text}'))

    def _ok(self, text: str) -> None:
        self.stdout.write(self.style.SUCCESS(f'  OK. {text}'))
