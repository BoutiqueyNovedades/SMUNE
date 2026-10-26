"""Route-level permission and tenant-isolation checks.

Run with: python -m unittest discover -s tests -v
"""

import os
import tempfile
import unittest

TEST_DATABASE_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault(
    "SMUNE_DATABASE_URI",
    "sqlite:///" + os.path.join(TEST_DATABASE_DIR.name, "security.db"),
)

from werkzeug.security import generate_password_hash

from app import (
    app,
    db,
    Cliente,
    Empresa,
    PermisoUsuario,
    Producto,
    Proveedor,
    UnidadNegocio,
    Usuario,
    Venta,
)

PASSWORD = "ClaveSegura99"


def _usuario(empresa, unidad, login, rol, modulos, **extra):
    usuario = Usuario(
        empresa_id=empresa.id if empresa else None,
        unidad_negocio_id=unidad.id if unidad else None,
        nombre=login,
        usuario=login,
        password=generate_password_hash(PASSWORD),
        rol=rol,
        activo=True,
        primer_acceso=False,
        administrador_principal=False,
        **extra,
    )
    db.session.add(usuario)
    db.session.flush()
    db.session.add_all(
        PermisoUsuario(usuario_id=usuario.id, modulo=m, puede_ver=True)
        for m in modulos
    )
    return usuario


class SecurityIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, SECRET_KEY="security-test-secret")
        db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "", 1)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with app.app_context():
            db.drop_all()
            db.create_all()
            empresas = []
            unidades = []
            for sufijo in ("a", "b"):
                empresa = Empresa(
                    codigo=f"EMP9{sufijo}", nombre=f"Empresa {sufijo}", giro="TIENDA"
                )
                db.session.add(empresa)
                db.session.flush()
                unidad = UnidadNegocio(
                    empresa_id=empresa.id, nombre=f"Sucursal {sufijo}"
                )
                db.session.add(unidad)
                db.session.flush()
                empresas.append(empresa)
                unidades.append(unidad)

            db.session.add(
                Usuario(
                    nombre="Principal",
                    usuario="principal",
                    password=generate_password_hash(PASSWORD),
                    rol="ADMIN",
                    activo=True,
                    primer_acceso=False,
                    administrador_principal=True,
                )
            )
            cls.empleado_a = _usuario(
                empresas[0], unidades[0], "empleado_a", "EMPLEADO",
                ["DASHBOARD", "VENTAS", "PRODUCTOS", "CLIENTES", "PROVEEDORES"],
            ).id
            cls.gerente_b = _usuario(
                empresas[1], None, "gerente_b", "GERENTE_EMPRESA",
                ["DASHBOARD", "REPORTES", "SEGURIDAD"],
            ).id
            _usuario(
                empresas[0], unidades[0], "inactivo_a", "EMPLEADO", ["DASHBOARD"]
            ).activo = False
            _usuario(
                empresas[0], unidades[0], "nuevo_a", "EMPLEADO", ["DASHBOARD"],
            ).primer_acceso = True

            producto_b = Producto(
                unidad_negocio_id=unidades[1].id, codigo="B-001", nombre="Producto B"
            )
            cliente_b = Cliente(unidad_negocio_id=unidades[1].id, nombre="Cliente B")
            venta_b = Venta(
                unidad_negocio_id=unidades[1].id, numero_venta="B-V-1", total=100,
                usuario_id=cls.gerente_b,
            )
            db.session.add_all([producto_b, cliente_b, venta_b])
            db.session.add(
                Proveedor(unidad_negocio_id=unidades[1].id, nombre="Proveedor B")
            )
            db.session.add(
                Proveedor(unidad_negocio_id=unidades[0].id, nombre="Proveedor A")
            )
            db.session.add(
                Cliente(unidad_negocio_id=unidades[0].id, nombre="Cliente A")
            )
            db.session.commit()
            cls.empresa_a, cls.empresa_b = empresas[0].id, empresas[1].id
            cls.unidad_a, cls.unidad_b = unidades[0].id, unidades[1].id
            cls.producto_b = producto_b.id
            cls.cliente_b = cliente_b.id
            cls.venta_b = venta_b.id

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.drop_all()
            db.session.remove()
            db.engine.dispose()

    def _cliente(self, usuario, password=PASSWORD):
        client = app.test_client()
        response = client.post(
            "/login", data={"usuario": usuario, "password": password}
        )
        return client, response

    def test_unauthenticated_requests_redirect_to_login(self):
        client = app.test_client()
        for url in ("/dashboard", "/ventas", "/usuarios", "/empresas"):
            response = client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login", response.headers["Location"], url)

    def test_inactive_user_cannot_log_in(self):
        client, response = self._cliente("inactivo_a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/dashboard").status_code, 302)
        self.assertIn("/login", client.get("/dashboard").headers["Location"])

    def test_first_access_forces_password_change_on_every_route(self):
        client, response = self._cliente("nuevo_a")
        self.assertIn("cambiar_password", response.headers["Location"])
        for url in ("/dashboard", "/ventas", "/mi-perfil"):
            self.assertIn(
                "cambiar_password", client.get(url).headers["Location"], url
            )
        response = client.post(
            "/cambiar_password",
            data={"password1": "OtraClave1234", "password2": "OtraClave1234"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get("/mi-perfil").status_code, 200)

        # Later logins no longer ask for a change.
        again, response = self._cliente("nuevo_a", "OtraClave1234")
        self.assertNotIn("cambiar_password", response.headers["Location"])

    def test_employee_without_module_permission_is_blocked_by_route(self):
        client, _ = self._cliente("empleado_a")
        for url in ("/compras", "/caja", "/reportes"):
            response = client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/dashboard", response.headers["Location"], url)

    def test_employee_cannot_reach_administration_routes(self):
        client, _ = self._cliente("empleado_a")
        for url in (
            "/empresas",
            f"/empresas/{self.empresa_a}/administrar",
            f"/unidades/{self.unidad_a}/usuarios",
            f"/unidades/{self.unidad_a}/usuarios/nuevo",
            f"/usuarios/{self.empleado_a}/permisos",
            "/panel-corporativo",
        ):
            self.assertEqual(client.get(url).status_code, 403, url)
        for url in (
            f"/usuarios/{self.gerente_b}/restablecer-password",
            f"/usuarios/{self.gerente_b}/estado",
            f"/usuarios/{self.gerente_b}/eliminar",
            f"/empresas/{self.empresa_a}/eliminar",
        ):
            self.assertEqual(client.post(url).status_code, 403, url)
        with app.app_context():
            self.assertTrue(db.session.get(Usuario, self.gerente_b).activo)

    def test_employee_cannot_access_other_company_records(self):
        client, _ = self._cliente("empleado_a")
        self.assertEqual(client.get(f"/ventas/{self.venta_b}").status_code, 403)
        self.assertEqual(
            client.get(f"/productos/editar/{self.producto_b}").status_code, 403
        )
        self.assertEqual(
            client.get(f"/productos/{self.producto_b}/movimientos").status_code, 403
        )
        self.assertIn(
            client.post(f"/ventas/cancelar/{self.venta_b}").status_code, (302, 403)
        )
        with app.app_context():
            self.assertEqual(db.session.get(Venta, self.venta_b).estado, "ACTIVA")
        listing = client.get("/productos").get_data(as_text=True)
        self.assertNotIn("Producto B", listing)

    def test_company_manager_cannot_cross_company_boundary(self):
        client, _ = self._cliente("gerente_b")
        self.assertEqual(
            client.get(f"/panel-corporativo/empresa/{self.empresa_b}").status_code, 200
        )
        self.assertEqual(
            client.get(f"/panel-corporativo/empresa/{self.empresa_a}").status_code, 403
        )
        self.assertEqual(
            client.get(f"/unidades/{self.unidad_a}/usuarios").status_code, 403
        )
        self.assertEqual(
            client.get(f"/reportes?empresa_id={self.empresa_a}").status_code, 403
        )

    def test_profile_lists_effective_permissions(self):
        client, _ = self._cliente("empleado_a")
        page = client.get("/mi-perfil").get_data(as_text=True)
        for modulo in ("VENTAS", "PRODUCTOS"):
            self.assertIn(modulo, page)
        self.assertNotIn("CAJA", page.replace("CAJA_", ""))

    def test_list_screens_show_only_own_unit_data(self):
        client, _ = self._cliente("empleado_a")
        proveedores = client.get("/proveedores")
        self.assertEqual(proveedores.status_code, 200)
        html = proveedores.get_data(as_text=True)
        self.assertIn("Proveedor A", html)
        self.assertNotIn("Proveedor B", html)
        html = client.get("/clientes").get_data(as_text=True)
        self.assertIn("Cliente A", html)
        self.assertNotIn("Cliente B", html)
        html = client.get("/ventas").get_data(as_text=True)
        self.assertNotIn("B-V-1", html)
        self.assertNotIn("operativo", html)

    def test_principal_sees_all_companies(self):
        client, _ = self._cliente("principal")
        self.assertEqual(client.get("/empresas").status_code, 200)
        self.assertEqual(
            client.get(f"/empresas/{self.empresa_b}/administrar").status_code, 200
        )


if __name__ == "__main__":
    unittest.main()
