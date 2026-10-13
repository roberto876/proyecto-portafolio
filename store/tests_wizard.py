"""Pruebas del asistente `preparar_produccion`.

La prueba de extremo a extremo ejecuta el asistente de verdad (subprocesos
reales de migrate, createsuperuser y seed_data) contra una base SQLite
temporal, porque en el entorno de pruebas no hay un Supabase disponible.
"""
import os
import sqlite3
import tempfile
from contextlib import closing
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from store.management.commands.preparar_produccion import Command

POOLER = 'postgresql://postgres.abcdef:clave-secreta@aws-0-sa-east-1.pooler.supabase.com:6543/postgres'


def query_one(database: Path, sql: str):
    """Consulta la base destino cerrando la conexión al terminar.

    En Windows un archivo SQLite abierto no se puede borrar ni reabrir desde
    otro proceso, y `with sqlite3.connect()` no cierra la conexión.
    """
    with closing(sqlite3.connect(database)) as conn:
        return conn.execute(sql).fetchall()


class DatabaseUrlValidationTests(SimpleTestCase):
    def check(self, url):
        return Command.validate_database_url(url)

    def test_direccion_de_pooler_valida(self):
        self.assertIsNone(self.check(POOLER))

    def test_rechaza_lo_que_no_es_postgres(self):
        self.assertIn('postgresql://', self.check('mysql://x'))

    def test_detecta_el_texto_de_ejemplo_sin_reemplazar(self):
        url = POOLER.replace('clave-secreta', '[YOUR-PASSWORD]')
        self.assertIn('[YOUR-PASSWORD]', self.check(url))

    def test_detecta_la_conexion_directa_ipv6(self):
        url = 'postgresql://postgres:clave@db.abcdef.supabase.co:5432/postgres'
        self.assertIn('Transaction pooler', self.check(url))

    def test_detecta_direccion_incompleta(self):
        self.assertIsNotNone(self.check('postgresql://pooler.supabase.com:6543/postgres'))

    def test_puerto_raro(self):
        self.assertIn('6543', self.check(POOLER.replace(':6543', ':9999')))

    def test_sqlite_solo_para_pruebas(self):
        self.assertIsNotNone(self.check('sqlite:///x.db'))
        self.assertIsNone(Command.validate_database_url('sqlite:///x.db', allow_sqlite=True))


class ErrorExplanationTests(SimpleTestCase):
    def test_contrasena_incorrecta(self):
        message = Command._explain_failure('FATAL: password authentication failed for user')
        self.assertIn('contraseña', message)

    def test_proyecto_en_pausa(self):
        self.assertIn('pausa', Command._explain_failure('connection timeout expired'))

    def test_error_desconocido_apunta_a_la_guia(self):
        self.assertIn('GUIA.md', Command._explain_failure('algo raro\nultima linea'))


class VercelEnvTests(SimpleTestCase):
    def test_bloque_con_las_variables_necesarias(self):
        block = Command.build_vercel_env(POOLER)
        keys = [line.split('=', 1)[0] for line in block.strip().splitlines()]
        self.assertEqual(keys, ['DJANGO_ENV', 'SECRET_KEY', 'DATABASE_URL',
                                'CRON_SECRET', 'TRANSBANK_ENVIRONMENT'])
        self.assertIn(f'DATABASE_URL={POOLER}', block)
        self.assertIn('DJANGO_ENV=production', block)

    def test_claves_nuevas_en_cada_ejecucion(self):
        first, second = Command.build_vercel_env(POOLER), Command.build_vercel_env(POOLER)

        def secret(block):
            return next(line for line in block.splitlines() if line.startswith('SECRET_KEY='))

        self.assertNotEqual(secret(first), secret(second))

    def test_sin_comentarios_para_pegar_directo(self):
        """Vercel acepta pegar el bloque: solo líneas CLAVE=valor."""
        for line in Command.build_vercel_env(POOLER).strip().splitlines():
            self.assertRegex(line, r'^[A-Z_]+=\S+$')

    def test_el_archivo_generado_esta_en_gitignore(self):
        gitignore = (Path(__file__).resolve().parent.parent / '.gitignore').read_text()
        self.assertIn('vercel-env.txt', gitignore.splitlines())


class WizardEndToEndTests(SimpleTestCase):
    """Ejecuta el asistente completo, con subprocesos reales."""

    def run_wizard(self, url, output, *, password='EntrenaFuerte2026', demo='si'):
        stdout = StringIO()
        with patch.dict(os.environ, {'DJANGO_SUPERUSER_PASSWORD': password}):
            call_command(
                'preparar_produccion',
                '--no-input', '--allow-sqlite',
                f'--database-url={url}',
                '--admin-username=duena', '--admin-email=duena@tienda.cl',
                f'--demo={demo}', f'--output={output}',
                stdout=stdout,
            )
        return stdout.getvalue()

    def test_asistente_completo_sin_preguntas(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            database = Path(tmp) / 'produccion.sqlite3'
            output = Path(tmp) / 'vercel-env.txt'
            url = 'sqlite:///' + database.as_posix()

            printed = self.run_wizard(url, output)

            # Tablas, administradora y catálogo creados en la base destino.
            admins = query_one(database, 'SELECT username, is_superuser FROM auth_user')
            products = query_one(database, 'SELECT COUNT(*) FROM store_product')[0][0]
            self.assertEqual(admins, [('duena', 1)])
            self.assertGreater(products, 0)

            # Archivo listo para pegar en Vercel.
            content = output.read_text(encoding='utf-8')
            self.assertIn(f'DATABASE_URL={url}', content)
            self.assertIn('SECRET_KEY=', content)
            self.assertIn('¡Todo listo en Supabase!', printed)

            # Segunda ejecución: idempotente, no duplica ni falla.
            self.run_wizard(url, output)
            self.assertEqual(
                query_one(database, 'SELECT COUNT(*) FROM store_product')[0][0], products,
            )
            self.assertEqual(query_one(database, 'SELECT COUNT(*) FROM auth_user')[0][0], 1)

    def test_contrasena_con_simbolos_que_rompen_la_url(self):
        url = 'postgresql://postgres.abc:cla#ve@aws-0-sa-east-1.pooler.supabase.com:6543/postgres'
        problem = Command.validate_database_url(url)
        self.assertIsNotNone(problem)

    def test_contrasena_debil_se_rechaza_antes_de_crear_el_usuario(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            url = 'sqlite:///' + (Path(tmp) / 'x.sqlite3').as_posix()
            with self.assertRaises(CommandError):
                self.run_wizard(url, Path(tmp) / 'out.txt', password='12345', demo='no')
            self.assertFalse((Path(tmp) / 'out.txt').exists())
