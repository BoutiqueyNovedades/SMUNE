"""Recorrido de todas las pantallas por rol: ninguna debe devolver 500 y el encabezado muestra empresa y sucursal."""

import unittest

from test_security_isolation import PASSWORD, _usuario, app, db  # noqa: E402  (sets the test DB)
from app import (
    Caja, Cliente, Compra, Empresa, Producto, Proveedor, UnidadNegocio, Usuario, Venta, DetalleVenta,
    CATALOGO_MODULOS,
)

TODOS = list(CATALOGO_MODULOS.keys()) if hasattr(CATALOGO_MODULOS, "keys") else [m["clave"] for m in CATALOGO_MODULOS]


class RecorridoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, SECRET_KEY="recorrido-secret")
        with app.app_context():
            db.drop_all()
            db.create_all()
            e = Empresa(codigo="RC-1", nombre="Boutique Aurora", giro="TIENDA")
            db.session.add(e)
            db.session.flush()
            u = UnidadNegocio(empresa_id=e.id, nombre="Sucursal Centro")
            db.session.add(u)
            db.session.flush()
            _usuario(e, u, "gerente_u", "GERENTE_UNIDAD", TODOS)
            _usuario(e, u, "cajero", "EMPLEADO", ["DASHBOARD", "CAJA", "VENTAS"])
            _usuario(e, None, "gerente_e", "GERENTE_EMPRESA", TODOS)
            p = _usuario(None, None, "principal_r", "ADMIN", [])
            p.administrador_principal = True
            prod = Producto(codigo="C1", nombre="Camisa", precio=100, unidad_negocio_id=u.id, activo=True)
            cli = Cliente(nombre="Ana", unidad_negocio_id=u.id, activo=True)
            prov = Proveedor(nombre="Textiles SA", unidad_negocio_id=u.id)
            db.session.add_all([prod, cli, prov])
            db.session.commit()
            cls.ids = dict(prod=prod.id, cli=cli.id, prov=prov.id, uni=u.id)

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.drop_all()
            db.session.remove()
            db.engine.dispose()

    def login(self, usuario):
        c = app.test_client()
        r = c.post("/login", data={"usuario": usuario, "password": PASSWORD})
        self.assertEqual(r.status_code, 302, usuario)
        return c

    def test_caja_flujo_completo(self):
        c = self.login("gerente_u")
        self.assertEqual(c.get("/caja").status_code, 200)
        self.assertEqual(c.get("/caja/abrir").status_code, 200)
        r = c.post("/caja/abrir", data={"fondo_inicial": "200"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/caja/movimiento").status_code, 200)
        c.post("/caja/movimiento", data={"tipo": "ENTRADA", "monto": "50", "observaciones": "x"})
        self.assertEqual(c.get("/caja/cerrar").status_code, 200)
        c.post("/caja/cerrar", data={"efectivo_real": "250"})
        r = c.get("/caja/corte")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/caja/jornada/", r.headers["Location"])
        self.assertEqual(c.get(r.headers["Location"]).status_code, 200)

    def test_jornada_gerente_empleado_y_bloqueo(self):
        import json
        from app import MovimientoCaja
        g = self.login("gerente_u")
        e = self.login("cajero")
        if g.get("/caja").status_code == 200 and "Realizar corte" in g.get("/caja").get_data(as_text=True):
            g.post("/caja/cerrar", data={"efectivo_real": "0"})
        # el empleado no puede abrir, mover ni cerrar
        for url, datos in (("/caja/abrir", {"fondo_inicial": "50"}),
                           ("/caja/movimiento", {"tipo": "SALIDA", "monto": "5"}),
                           ("/caja/cerrar", {"efectivo_real": "1"})):
            self.assertEqual(e.post(url, data=datos).status_code, 302)
        with app.app_context():
            self.assertIsNone(Caja.query.filter_by(abierta=True).first())
        # sin caja abierta el empleado no vende
        carrito = json.dumps([{"producto_id": self.ids["prod"], "cantidad": 1}])
        r = e.post("/ventas/nueva", data={"carrito": carrito, "metodo_pago": "EFECTIVO"})
        self.assertIn("/caja", r.headers["Location"])
        self.assertNotIn("/caja/abrir", r.headers["Location"])
        # el gerente abre; las ventas se acumulan
        g.post("/caja/abrir", data={"fondo_inicial": "100"})
        with app.app_context():
            from app import mover_inventario
            nuevo = Producto(codigo="C2", nombre="Blusa", precio=100, unidad_negocio_id=self.ids["uni"], activo=True)
            db.session.add(nuevo)
            db.session.flush()
            pid = nuevo.id
            mover_inventario(pid, self.ids["uni"], 10, "COMPRA", 1, "T", "stock")
            db.session.commit()
        carrito = json.dumps([{"producto_id": pid, "cantidad": 1}])
        r1 = e.post("/ventas/nueva", data={"carrito": carrito, "metodo_pago": "EFECTIVO"})
        r2 = e.post("/ventas/nueva", data={"carrito": carrito, "metodo_pago": "EFECTIVO"})
        self.assertEqual(r1.status_code, 302)
        with app.app_context():
            caja = Caja.query.filter_by(abierta=True).first()
            self.assertEqual(caja.saldo_actual, 300)
            caja_id = caja.id
        venta_url = r1.headers["Location"]
        venta_id = int(venta_url.rstrip("/").split("/")[-1])
        # corte del gerente
        g.post("/caja/cerrar", data={"efectivo_real": "300"})
        with app.app_context():
            c = db.session.get(Caja, caja_id)
            self.assertFalse(c.abierta)
            self.assertEqual(c.diferencia, 0)
        # jornada cerrada: no se edita ni se cancela
        self.assertEqual(g.post(f"/ventas/editar/{venta_id}", data={}).status_code, 302)
        with app.app_context():
            self.assertEqual(db.session.get(Venta, venta_id).estado, "ACTIVA")
        self.login("principal_r")
        g.post(f"/ventas/cancelar/{venta_id}")
        self.login("principal_r").post(f"/ventas/cancelar/{venta_id}")
        with app.app_context():
            self.assertEqual(db.session.get(Venta, venta_id).estado, "ACTIVA")
            self.assertEqual(db.session.get(Caja, caja_id).saldo_actual, 300)
        # el empleado ve el esperado, no contado/diferencia
        html = e.get(f"/caja/jornada/{caja_id}").get_data(as_text=True)
        self.assertIn("Debe tener en caja", html)
        self.assertNotIn("Registro de movimientos", html)
        html = g.get(f"/caja/jornada/{caja_id}").get_data(as_text=True)
        self.assertIn("Registro de movimientos", html)
        self.assertEqual(g.get("/caja/historial").status_code, 200)
        # el gerente de empresa ve el consolidado; otra empresa no
        ge = self.login("gerente_e")
        self.assertEqual(ge.get(f"/caja/jornada/{caja_id}").status_code, 200)
        self.assertIn("Sucursal Centro", ge.get("/caja/historial").get_data(as_text=True))

    def test_recorrido_get_por_rol(self):
        urls = [
            "/dashboard", "/mi-perfil", "/productos", "/clientes", "/proveedores", "/ventas",
            "/compras", "/caja", "/reportes", "/alertas", "/apartados", "/configuracion",
            "/ventas/nueva", "/compras/nueva", "/clientes/nuevo", "/productos/nuevo",
            f"/clientes/{self.ids['cli']}", f"/clientes/{self.ids['cli']}/puntos",
            f"/productos/{self.ids['prod']}/movimientos", "/inventario",
            "/proveedores/nuevo", f"/proveedores/{self.ids['prov']}", "/dashboard/ejecutivo",
            "/reportes/diario", "/reportes/mensual",
        ]
        for usuario in ("gerente_u", "cajero", "gerente_e", "principal_r"):
            c = self.login(usuario)
            for url in urls:
                r = c.get(url)
                self.assertLess(r.status_code, 500, f"{usuario} {url}")

    def test_encabezado_empresa_sucursal(self):
        html = self.login("gerente_u").get("/dashboard", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Boutique Aurora", html)
        self.assertIn("Sucursal Centro", html)
        html = self.login("gerente_e").get("/dashboard", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Boutique Aurora", html)
        self.assertIn("Todas las sucursales", html)
        html = self.login("principal_r").get("/dashboard", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Todas las empresas", html)

    def test_venta_completa(self):
        import json
        from app import Inventario, MovimientoCaja
        with app.app_context():
            from app import mover_inventario
            mover_inventario(self.ids["prod"], self.ids["uni"], 10, "COMPRA", 1, "T", "stock")
            db.session.commit()
        c = self.login("gerente_u")
        r = c.post("/ventas/nueva", data={"carrito": json.dumps([{"producto_id": self.ids["prod"], "cantidad": 2}]),
                                          "metodo_pago": "EFECTIVO"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/caja/abrir", r.headers["Location"])
        c.post("/caja/abrir", data={"fondo_inicial": "100"})
        self.assertEqual(c.get("/ventas/nueva").status_code, 200)
        r = c.post("/ventas/nueva", data={"carrito": json.dumps([{"producto_id": self.ids["prod"], "cantidad": 2}]),
                                          "metodo_pago": "EFECTIVO", "cliente_id": self.ids["cli"]})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/ventas/", r.headers["Location"])
        self.assertEqual(c.get(r.headers["Location"]).status_code, 200)
        with app.app_context():
            from app import stock_producto
            self.assertEqual(stock_producto(self.ids["prod"], self.ids["uni"]), 8)
            self.assertEqual(Caja.query.filter_by(abierta=True).first().saldo_actual, 300)
        r = c.post("/ventas/nueva", data={"carrito": json.dumps([{"producto_id": self.ids["prod"], "cantidad": 99}]),
                                          "metodo_pago": "EFECTIVO"})
        with app.app_context():
            self.assertEqual(stock_producto(self.ids["prod"], self.ids["uni"]), 8)

    def test_logo_dashboard_y_retencion(self):
        import io
        from datetime import datetime, timedelta
        p = self.login("principal_r")
        with app.app_context():
            empresa_id = Empresa.query.filter_by(codigo="RC-1").first().id
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
        r = p.post("/logotipos", data={"tipo": "empresa", "id": empresa_id,
                                       "logo": (io.BytesIO(png), "logo.png")},
                   content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        r = p.post("/logotipos", data={"tipo": "empresa", "id": empresa_id,
                                       "logo": (io.BytesIO(b"x"), "x.svg")},
                   content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        for usuario in ("gerente_u", "cajero", "gerente_e"):
            html = self.login(usuario).get("/dashboard").get_data(as_text=True)
            self.assertIn("uploads/logos/empresa_", html, usuario)
            self.assertNotIn("Ventas de hoy", html)
        self.assertEqual(self.login("cajero").get("/logotipos").status_code, 403)
        # vigencia: empleado 2 meses, gerente 3, principal todo
        with app.app_context():
            u = UnidadNegocio.query.first()
            for dias in (45, 75, 120):
                db.session.add(Caja(unidad_negocio_id=u.id, usuario_id=1, fondo_inicial=0,
                                    saldo_actual=0, abierta=False,
                                    fecha_apertura=datetime.now() - timedelta(days=dias),
                                    fecha_cierre=datetime.now() - timedelta(days=dias)))
            db.session.commit()
        def cuenta(usuario):
            html = self.login(usuario).get("/caja/historial").get_data(as_text=True)
            return html.count("/caja/jornada/")
        n_emp, n_ger, n_pri = cuenta("cajero"), cuenta("gerente_u"), cuenta("principal_r")
        self.assertEqual(n_ger - n_emp, 1)
        self.assertEqual(n_pri - n_ger, 1)
        # el principal ajusta la vigencia del empleado
        with app.app_context():
            from app import Usuario
            cid = Usuario.query.filter_by(usuario="cajero").first().id
        p.post("/caja/retencion", data={"usuario_id": cid, "meses": 6})
        self.assertEqual(cuenta("cajero"), n_pri)
        r = p.get("/caja/historial/exportar")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.content_type)
        self.assertEqual(self.login("gerente_u").get("/caja/historial/exportar").status_code, 403)

    def test_apartados_flujo(self):
        import json
        from datetime import date, timedelta
        from app import Apartado, mover_inventario, stock_producto
        g = self.login("gerente_u")
        if "Realizar corte" in g.get("/caja").get_data(as_text=True):
            g.post("/caja/cerrar", data={"efectivo_real": "0"})
        with app.app_context():
            nuevo = Producto(codigo="C3", nombre="Falda", precio=200,
                             unidad_negocio_id=self.ids["uni"], activo=True)
            db.session.add(nuevo)
            db.session.flush()
            pid = nuevo.id
            mover_inventario(pid, self.ids["uni"], 5, "COMPRA", 1, "T", "stock")
            db.session.commit()
        self.assertEqual(g.get("/apartados").status_code, 200)
        self.assertEqual(g.get("/apartados/nuevo").status_code, 200)
        datos = {
            "carrito": json.dumps([{"producto_id": pid, "cantidad": 2}]),
            "cliente_id": self.ids["cli"], "anticipo": "100",
            "fecha_vencimiento": (date.today() + timedelta(days=10)).isoformat(),
        }
        # con caja cerrada no se registra
        g.post("/apartados/nuevo", data=datos)
        with app.app_context():
            self.assertEqual(Apartado.query.count(), 0)
        g.post("/caja/abrir", data={"fondo_inicial": "0"})
        r = g.post("/apartados/nuevo", data=datos)
        aid = int(r.headers["Location"].rstrip("/").split("/")[-1])
        with app.app_context():
            a = db.session.get(Apartado, aid)
            self.assertEqual((a.total, a.saldo, a.estado), (400, 300, "ACTIVO"))
            self.assertEqual(stock_producto(pid, self.ids["uni"]), 3)
            self.assertEqual(Caja.query.filter_by(abierta=True).first().saldo_actual, 100)
        self.assertEqual(g.get(f"/apartados/{aid}").status_code, 200)
        self.assertEqual(g.get(f"/apartados/{aid}/cambiar").status_code, 200)
        g.post(f"/apartados/{aid}/abonar", data={"monto": "300", "metodo_pago": "EFECTIVO"})
        with app.app_context():
            self.assertEqual(db.session.get(Apartado, aid).estado, "LIQUIDADO")
        g.post(f"/apartados/{aid}/entregar")
        with app.app_context():
            self.assertEqual(db.session.get(Apartado, aid).estado, "ENTREGADO")
        # cancelar uno activo devuelve inventario
        datos["anticipo"] = "80"
        datos["carrito"] = json.dumps([{"producto_id": pid, "cantidad": 1}])
        r = g.post("/apartados/nuevo", data=datos)
        aid2 = int(r.headers["Location"].rstrip("/").split("/")[-1])
        self.assertEqual(g.get(f"/apartados/{aid2}").status_code, 200)
        g.post(f"/apartados/{aid2}/cancelar")
        with app.app_context():
            self.assertEqual(db.session.get(Apartado, aid2).estado, "CANCELADO")
            self.assertEqual(stock_producto(pid, self.ids["uni"]), 3)
        self.assertIn(self.login("cajero").get(f"/apartados/{aid}").status_code, (302, 403))
        html = g.get("/dashboard").get_data(as_text=True)
        self.assertIn("Apartados", html)
        g.post("/caja/cerrar", data={"efectivo_real": "0"})

    def test_menu_principal_y_secciones_unidad(self):
        with app.app_context():
            uid = UnidadNegocio.query.first().id
        html = self.login("principal_r").get("/dashboard").get_data(as_text=True)
        self.assertIn("Empresas", html)
        for texto in ("Productos</a>", "Proveedores</a>", "Compras</a>"):
            self.assertNotIn(texto, html.replace("\n", "").replace("  ", ""))
        for usuario in ("principal_r", "gerente_e"):
            c = self.login(usuario)
            for sec in ("ventas", "compras", "productos", "clientes", "proveedores",
                        "apartados", "usuarios"):
                self.assertEqual(
                    c.get(f"/panel-corporativo/unidad/{uid}/{sec}").status_code, 200, (usuario, sec))
            self.assertEqual(
                c.get(f"/panel-corporativo/unidad/{uid}/cajas").status_code, 302)
        self.assertEqual(
            self.login("cajero").get(f"/panel-corporativo/unidad/{uid}/ventas").status_code, 403)

    def test_caja_sin_unidad_redirige(self):
        c = self.login("gerente_e")
        self.assertEqual(c.get("/caja").status_code, 302)

    def test_recorrido_de_menus(self):
        import re
        for usuario in ("principal_r", "gerente_u", "cajero", "gerente_e"):
            c = self.login(usuario)
            html = c.get("/dashboard").get_data(as_text=True)
            rutas = {h for h in re.findall(r'href="(/[^"#]*)"', html)
                     if not h.startswith("/static") and h != "/logout"}
            self.assertTrue(rutas, usuario)
            for ruta in sorted(rutas):
                r = c.get(ruta, follow_redirects=True)
                self.assertLess(r.status_code, 500, (usuario, ruta))
                self.assertNotEqual(r.status_code, 404, (usuario, ruta))

    def test_configuracion_respaldo_y_acceso(self):
        import tempfile
        from datetime import datetime
        from app import Usuario
        app.config["RESPALDOS_DIR"] = tempfile.mkdtemp()
        p = self.login("principal_r")
        self.assertEqual(p.get("/configuracion").status_code, 302)
        r = p.get("/configuracion/sistema")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Respaldos", r.get_data(as_text=True))
        self.assertEqual(self.login("gerente_u").get("/configuracion/sistema").status_code, 403)
        # respaldo, cambio posterior, restauración
        p.post("/configuracion/respaldo/crear")
        nombre = [n for n in __import__("os").listdir(app.config["RESPALDOS_DIR"]) if n.endswith("_manual.zip")][0]
        with app.app_context():
            db.session.add(Cliente(nombre="Posterior", unidad_negocio_id=self.ids["uni"], activo=True))
            db.session.commit()
        p.post("/configuracion/respaldo/restaurar", data={"nombre": nombre, "confirmacion": "no"})
        with app.app_context():
            self.assertIsNotNone(Cliente.query.filter_by(nombre="Posterior").first())
        p.post("/configuracion/respaldo/restaurar", data={"nombre": nombre, "confirmacion": "RESTAURAR"})
        with app.app_context():
            self.assertIsNone(Cliente.query.filter_by(nombre="Posterior").first())
            self.assertIsNotNone(Usuario.query.filter_by(usuario="cajero").first())
        self.assertTrue(any("pre_restauracion" in n for n in __import__("os").listdir(app.config["RESPALDOS_DIR"])))
        # pausa
        cajero = self.login("cajero")
        p.post("/configuracion/acceso", data={"ambito": "pausa", "pausado": "on", "mensaje": "Mantenimiento"})
        r = cajero.get("/dashboard", follow_redirects=True)
        self.assertIn("Mantenimiento", r.get_data(as_text=True))
        self.assertEqual(p.get("/dashboard").status_code, 200)
        p.post("/configuracion/acceso", data={"ambito": "pausa"})
        # horario fuera de turno
        ahora = datetime.now()
        otro = f"{(ahora.hour + 12) % 24:02d}:00"
        p.post("/configuracion/acceso", data={
            "ambito": "global", "activo": "on", "inicio": otro, "fin": otro,
            "dias": [str(d) for d in range(7)]})
        self.assertEqual(app.test_client().post(
            "/login", data={"usuario": "cajero", "password": PASSWORD}).status_code, 200)
        p.post("/configuracion/acceso", data={"ambito": "global"})
        self.assertEqual(self.login("cajero").get("/dashboard").status_code, 200)

    def test_bloqueo_por_intentos(self):
        p = self.login("principal_r")
        with app.app_context():
            uni, emp = UnidadNegocio.query.first().id, Empresa.query.first().id
        cajero = self.login("cajero")
        p.post(f"/configuracion/acceso/unidad/{uni}")
        self.assertEqual(cajero.get("/dashboard").status_code, 302)
        self.assertEqual(self.login_fallido("cajero"), 200)
        p.post(f"/configuracion/acceso/unidad/{uni}")
        p.post(f"/configuracion/acceso/empresa/{emp}")
        self.assertEqual(self.login_fallido("cajero"), 200)
        p.post(f"/configuracion/acceso/empresa/{emp}")
        with app.app_context():
            uid = Usuario.query.filter_by(usuario="cajero").first().id
        p.post(f"/configuracion/acceso/usuario/{uid}")
        self.assertEqual(self.login_fallido("cajero"), 200)
        p.post(f"/configuracion/acceso/usuario/{uid}")
        self.assertEqual(self.login("cajero").get("/dashboard").status_code, 200)
        self.assertIn("Abrir / cerrar acceso", p.get("/configuracion/sistema").get_data(as_text=True))

    def login_fallido(self, usuario):
        return app.test_client().post("/login", data={"usuario": usuario, "password": PASSWORD}).status_code

    def test_bloqueo_global_y_intentos(self):
        p = self.login("principal_r")
        cajero = self.login("cajero")
        p.post("/configuracion/acceso/alternar")
        self.assertIn("CERRADO", p.get("/dashboard").get_data(as_text=True))
        self.assertEqual(app.test_client().post(
            "/login", data={"usuario": "cajero", "password": PASSWORD}).status_code, 200)
        self.assertEqual(cajero.get("/dashboard").status_code, 302)
        p.post("/configuracion/acceso/alternar")
        self.assertIn("ABIERTO", p.get("/dashboard").get_data(as_text=True))
        self.assertEqual(self.login("cajero").get("/dashboard").status_code, 200)
        self.assertEqual(self.login("cajero").post("/configuracion/acceso/alternar").status_code, 403)
        c = app.test_client()
        for _ in range(5):
            c.post("/login", data={"usuario": "intruso", "password": "mal"})
        self.assertEqual(c.post("/login", data={"usuario": "intruso", "password": PASSWORD}).status_code, 429)
        self.assertEqual(self.login("cajero").get("/dashboard").status_code, 200)


if __name__ == "__main__":
    unittest.main()
