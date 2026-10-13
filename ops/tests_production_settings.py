"""Mensajes de configuración que vería el cliente en Vercel.

Arrancan Django en modo producción como un proceso aparte, igual que Vercel,
con los errores de configuración más probables.
"""
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

POOLER = 'postgresql://postgres.abc:clave@aws-0-sa-east-1.pooler.supabase.com:6543/postgres'
SECRET = 'clave-larga-y-aleatoria-de-prueba-0123456789abcdef'


def boot_production(**env) -> str:
    """Ejecuta `manage.py check` en producción y devuelve la salida completa."""
    clean = {k: v for k, v in os.environ.items()
             if k not in ('SECRET_KEY', 'DATABASE_URL', 'TEST_DATABASE_URL')}
    result = subprocess.run(
        [sys.executable, 'manage.py', 'check'],
        cwd=settings.BASE_DIR,
        env={**clean, 'DJANGO_ENV': 'production', **env},
        capture_output=True, text=True,
    )
    return (result.stdout or '') + (result.stderr or '')


class ProductionMessagesTests(SimpleTestCase):
    def test_falta_la_clave_secreta(self):
        output = boot_production(DATABASE_URL=POOLER)
        self.assertIn('FALTA SECRET_KEY', output)
        self.assertIn('GUIA.md, Parte 2, paso 5', output)

    def test_falta_la_base_de_datos(self):
        output = boot_production(SECRET_KEY=SECRET)
        self.assertIn('FALTA DATABASE_URL', output)

    def test_contrasena_sin_reemplazar(self):
        output = boot_production(
            SECRET_KEY=SECRET, DATABASE_URL=POOLER.replace('clave', '[YOUR-PASSWORD]'),
        )
        self.assertIn('todavía tiene el texto [YOUR-PASSWORD]', output)
        self.assertNotIn('ParseError', output.splitlines()[-1])

    def test_contrasena_con_simbolos(self):
        output = boot_production(SECRET_KEY=SECRET, DATABASE_URL=POOLER.replace('clave', 'cla#ve'))
        self.assertIn('solo letras y números', output)

    def test_transbank_produccion_sin_credenciales(self):
        output = boot_production(
            SECRET_KEY=SECRET, DATABASE_URL=POOLER, TRANSBANK_ENVIRONMENT='production',
        )
        self.assertIn('FALTA TRANSBANK_COMMERCE_CODE', output)

    def test_configuracion_correcta_arranca(self):
        output = boot_production(
            SECRET_KEY=SECRET, DATABASE_URL=POOLER,
            VERCEL_PROJECT_PRODUCTION_URL='mi-tienda.vercel.app',
        )
        self.assertIn('no issues', output)

    def test_ningun_mensaje_apunta_a_documentos_inexistentes(self):
        root = Path(settings.BASE_DIR)
        self.assertTrue((root / 'GUIA.md').exists())
        missing_doc = 'DESPLIEGUE' + '.md'  # Partido para no autodelatar este test.
        for path in root.rglob('*.py'):
            # Los archivos de prueba nombran el documento inexistente a propósito.
            if 'venv' in path.parts or path.name.startswith('test'):
                continue
            self.assertNotIn(missing_doc, path.read_text(encoding='utf-8', errors='ignore'),
                             msg=f'{path} menciona un documento que no existe')
