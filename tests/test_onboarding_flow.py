"""End-to-end onboarding exercise using a disposable SQLite database.

Run with: python -m unittest discover -s tests -v
"""

import os
import re
import tempfile
import unittest
from unittest.mock import patch

TEST_DATABASE_DIR = tempfile.TemporaryDirectory()
os.environ["SMUNE_DATABASE_URI"] = (
    "sqlite:///" + os.path.join(TEST_DATABASE_DIR.name, "onboarding.db")
)

from app import (
    app,
    db,
    Empresa,
    UnidadNegocio,
    Usuario,
    PermisoUsuario,
    inicializar_sistema,
)


class OnboardingFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(
            TESTING=True,
            SECRET_KEY="onboarding-test-secret",
        )
        with patch.dict(
            os.environ,
            {"SMUNE_ADMIN_USER": "admin", "SMUNE_ADMIN_PASSWORD": "Tienda00"},
        ):
            with app.app_context():
                db.create_all()
                # A fresh install starts tenant-empty and creates only the principal.
                inicializar_sistema(db, Empresa, UnidadNegocio, Usuario, None)

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.drop_all()
            db.session.remove()
            db.engine.dispose()
        TEST_DATABASE_DIR.cleanup()

    def setUp(self):
        self.client = app.test_client()
        with app.app_context():
            self.assertEqual(Empresa.query.count(), 0)
            self.assertEqual(UnidadNegocio.query.count(), 0)
            self.assertEqual(Usuario.query.filter_by(administrador_principal=True).count(), 1)

    def _login_and_change_initial_password(self, client, username, password, new_password):
        response = client.post(
            "/login",
            data={"usuario": username, "password": password},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("cambiar_password", response.headers["Location"])
        response = client.post(
            "/cambiar_password",
            data={"password1": new_password, "password2": new_password},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_company_branch_roles_permissions_reset_and_reports(self):
        # Principal logs in; first-run password change is mandatory.
        self._login_and_change_initial_password(
            self.client, "admin", "Tienda00", "PrincipalNueva99"
        )

        # Create a company only; it must not create an implicit branch or manager.
        response = self.client.post(
            "/empresas/nueva",
            data={
                "nombre": "Comercial de Prueba",
                "giro": "Comercio minorista",
                "razon_social": "Comercial de Prueba SA de CV",
                "rfc": "XAXX010101000",
                "telefono": "5550101010",
                "correo": "prueba@example.com",
                "direccion": "Calle Uno 123",
                "ciudad": "Puebla",
                "estado": "Puebla",
                "pais": "México",
                "codigo_postal": "72000",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            empresa = Empresa.query.filter_by(nombre="Comercial de Prueba").one()
            empresa_id = empresa.id
            self.assertEqual(empresa.giro, "TIENDA")
            self.assertEqual(UnidadNegocio.query.filter_by(empresa_id=empresa.id).count(), 0)
            self.assertEqual(
                Usuario.query.filter_by(empresa_id=empresa.id).count(), 0
            )

        # An optional company manager is created from company administration,
        # not as a side effect of company creation.
        response = self.client.post(
            f"/empresas/{empresa_id}/gerente/nuevo",
            data={
                "nombre": "Gerente Corporativo",
                "usuario": "gerente_empresa",
                "password": "TempCorporativo99",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        company_manager = app.test_client()
        self._login_and_change_initial_password(
            company_manager,
            "gerente_empresa",
            "TempCorporativo99",
            "CorporativoNueva99",
        )
        self.assertEqual(company_manager.get("/dashboard").status_code, 200)
        self.assertEqual(
            company_manager.get(f"/panel-corporativo/empresa/{empresa_id}").status_code,
            200,
        )
        self.assertEqual(
            company_manager.get(f"/reportes?empresa_id={empresa_id}").status_code,
            200,
        )

        # Create the first branch under that company.
        response = self.client.post(
            f"/empresas/{empresa_id}/unidades/nueva",
            data={
                "nombre": "Sucursal Centro",
                "direccion": "Av. Reforma 45",
                "telefono": "5550202020",
                "correo": "centro@example.com",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            unidad = UnidadNegocio.query.filter_by(
                empresa_id=empresa_id, nombre="Sucursal Centro"
            ).one()
            unidad_id = unidad.id
            self.assertIsNotNone(
                __import__("app").Configuracion.query.filter_by(
                    unidad_negocio_id=unidad_id
                ).first()
            )
        self.assertEqual(
            self.client.get(f"/unidades/{unidad_id}/usuarios/nuevo").status_code,
            200,
        )

        # Principal creates the branch manager with explicit module permissions.
        manager_permissions = ["DASHBOARD", "VENTAS", "REPORTES", "SEGURIDAD"]
        response = self.client.post(
            f"/unidades/{unidad_id}/usuarios/nuevo",
            data={
                "nombre": "Gerente Sucursal",
                "usuario": "gerente_centro",
                "password": "TempGerente99",
                "rol": "ADMIN",
                "modulos": manager_permissions,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            gerente = Usuario.query.filter_by(usuario="gerente_centro").one()
            gerente_id = gerente.id
            self.assertEqual(gerente.rol, "ADMIN")
            self.assertEqual(gerente.unidad_negocio_id, unidad_id)
            self.assertEqual(
                {p.modulo for p in gerente.permisos}, set(manager_permissions)
            )

        # The manager completes first login and can create a supervisor, but not another manager.
        manager_client = app.test_client()
        self._login_and_change_initial_password(
            manager_client, "gerente_centro", "TempGerente99", "GerenteNueva99"
        )
        response = manager_client.post(
            f"/unidades/{unidad_id}/usuarios/nuevo",
            data={
                "nombre": "Supervisora",
                "usuario": "supervisora_centro",
                "password": "TempSuper99",
                "rol": "SUPERVISOR",
                "modulos": ["DASHBOARD", "VENTAS", "REPORTES"],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        employee_response = manager_client.post(
            f"/unidades/{unidad_id}/usuarios/nuevo",
            data={
                "nombre": "Empleado",
                "usuario": "empleado_centro",
                "password": "TempEmpleado99",
                "rol": "EMPLEADO",
                "modulos": ["DASHBOARD", "VENTAS"],
            },
            follow_redirects=False,
        )
        self.assertEqual(employee_response.status_code, 302)
        with app.app_context():
            supervisora = Usuario.query.filter_by(usuario="supervisora_centro").one()
            supervisora_id = supervisora.id
            self.assertEqual(supervisora.rol, "SUPERVISOR")
            self.assertEqual(
                {p.modulo for p in supervisora.permisos},
                {"DASHBOARD", "VENTAS", "REPORTES"},
            )
            empleado = Usuario.query.filter_by(usuario="empleado_centro").one()
            self.assertEqual(empleado.rol, "EMPLEADO")
            self.assertEqual({p.modulo for p in empleado.permisos}, {"DASHBOARD", "VENTAS"})

        denied = manager_client.post(
            f"/unidades/{unidad_id}/usuarios/nuevo",
            data={
                "nombre": "Gerente no autorizado",
                "usuario": "gerente_no_autorizado",
                "password": "Temporal99",
                "rol": "ADMIN",
                "modulos": ["DASHBOARD"],
            },
            follow_redirects=False,
        )
        self.assertEqual(denied.status_code, 302)
        with app.app_context():
            self.assertIsNone(Usuario.query.filter_by(usuario="gerente_no_autorizado").first())

        # The module guard uses assigned permissions: REPORTES works for the supervisor.
        supervisor_client = app.test_client()
        self._login_and_change_initial_password(
            supervisor_client, "supervisora_centro", "TempSuper99", "SuperNueva99"
        )
        self.assertEqual(supervisor_client.get("/reportes").status_code, 200)
        self.assertEqual(
            supervisor_client.get("/reportes?empresa_id=999999").status_code,
            403,
        )

        # Principal can reset the supervisor password; it is one-time and force-change.
        response = self.client.post(
            f"/usuarios/{supervisora_id}/restablecer-password",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        match = re.search(r"Contraseña temporal de supervisora_centro: ([A-Za-z0-9_-]+)", text)
        self.assertIsNotNone(match)
        temporary_password = match.group(1)
        with app.app_context():
            supervisora = db.session.get(Usuario, supervisora_id)
            self.assertTrue(supervisora.primer_acceso)

        reset_client = app.test_client()
        login_response = reset_client.post(
            "/login",
            data={"usuario": "supervisora_centro", "password": temporary_password},
            follow_redirects=False,
        )
        self.assertIn("cambiar_password", login_response.headers["Location"])

        # The same report supports both company and branch scopes.
        self.assertEqual(
            self.client.get(f"/reportes?empresa_id={empresa_id}").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/reportes?empresa_id={empresa_id}&unidad_id={unidad_id}"
            ).status_code,
            200,
        )
        excel = self.client.get(
            f"/reportes/exportar/excel?empresa_id={empresa_id}&unidad_id={unidad_id}"
        )
        pdf = self.client.get(
            f"/reportes/exportar/pdf?empresa_id={empresa_id}&unidad_id={unidad_id}"
        )
        self.assertEqual(excel.status_code, 200)
        self.assertEqual(pdf.status_code, 200)
        self.assertIn("spreadsheetml", excel.mimetype)
        self.assertEqual(pdf.mimetype, "application/pdf")


if __name__ == "__main__":
    unittest.main()
