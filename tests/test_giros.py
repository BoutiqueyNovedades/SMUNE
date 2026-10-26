"""Restaurant and manufacturing flows, permissions and tenant isolation."""

import unittest

from test_security_isolation import PASSWORD, _usuario, app, db  # noqa: E402  (sets the test DB)
from app import (
    Caja, Cliente, Empresa, Insumo, ListaMaterial, Mesa, MovimientoInsumo,
    OrdenProduccion, Pedido, Platillo, Producto, UnidadNegocio, Usuario, stock_producto,
)

TODOS_REST = [
    "DASHBOARD", "MENU", "RECETAS_RESTAURANTE", "PEDIDOS", "COCINA", "MERMA_RESTAURANTE",
    "COMPRAS", "REPORTES", "CAJA",
]
TODOS_FAB = [
    "DASHBOARD", "MATERIAS_PRIMAS", "RECETAS_FABRICACION", "ORDENES_PRODUCCION",
    "PROCESOS_FABRICACION", "COSTOS_FABRICACION", "COMPRAS", "REPORTES",
]


class GirosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, SECRET_KEY="giros-test-secret")
        with app.app_context():
            db.drop_all()
            db.create_all()
            cls.ids = {}
            for clave, giro in (("r1", "RESTAURANTE"), ("r2", "RESTAURANTE"), ("f1", "FABRICACION"), ("t1", "TIENDA")):
                e = Empresa(codigo=f"G-{clave}", nombre=f"Empresa {clave}", giro=giro)
                db.session.add(e)
                db.session.flush()
                u = UnidadNegocio(empresa_id=e.id, nombre=f"Unidad {clave}")
                db.session.add(u)
                db.session.flush()
                cls.ids[clave] = (e.id, u.id)
            e_r1, u_r1 = cls.ids["r1"]
            e_r2, u_r2 = cls.ids["r2"]
            e_f, u_f = cls.ids["f1"]
            e_t, u_t = cls.ids["t1"]
            Empresa_ = Empresa
            ger_r = _usuario(Empresa_.query.get(e_r1), None, "ger_r", "GERENTE_EMPRESA", TODOS_REST)
            _usuario(Empresa_.query.get(e_r1), UnidadNegocio.query.get(u_r1), "mesero_r", "EMPLEADO", ["DASHBOARD", "PEDIDOS"])
            _usuario(Empresa_.query.get(e_r2), UnidadNegocio.query.get(u_r2), "ger_r2", "GERENTE_UNIDAD", TODOS_REST)
            _usuario(Empresa_.query.get(e_f), None, "ger_f", "GERENTE_EMPRESA", TODOS_FAB)
            _usuario(Empresa_.query.get(e_f), UnidadNegocio.query.get(u_f), "obrero_f", "EMPLEADO", ["DASHBOARD", "ORDENES_PRODUCCION"])
            _usuario(Empresa_.query.get(e_t), UnidadNegocio.query.get(u_t), "ger_t", "GERENTE_UNIDAD", TODOS_REST + TODOS_FAB)
            principal = _usuario(None, None, "principal_g", "ADMIN", [])
            principal.administrador_principal = True
            db.session.flush()
            db.session.add(Caja(unidad_negocio_id=u_r1, usuario_id=ger_r.id, fondo_inicial=100, saldo_actual=100, abierta=True))
            db.session.commit()

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

    def post(self, c, url, **data):
        return c.post(url, data=data)

    # ------------------------------------------------------------ visibilidad
    def test_modules_visible_per_giro(self):
        c = self.login("ger_r")
        html = c.get("/dashboard", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Mesas y pedidos", html)
        self.assertNotIn("Órdenes de producción", html)
        c = self.login("ger_f")
        html = c.get("/dashboard", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Órdenes de producción", html)
        self.assertNotIn("Mesas y pedidos", html)

    def test_routes_enforce_giro_and_permissions(self):
        mesero = self.login("mesero_r")
        self.assertEqual(mesero.get("/restaurante/pedidos").status_code, 200)
        for url in ("/restaurante/menu", "/restaurante/cocina", "/restaurante/reportes",
                    "/restaurante/insumos", "/fabricacion/ordenes"):
            self.assertIn(mesero.get(url).status_code, (302, 403), url)
        # La tienda no tiene módulos de restaurante aunque el usuario tenga el permiso
        tienda = self.login("ger_t")
        for url in ("/restaurante/pedidos", "/fabricacion/ordenes"):
            self.assertIn(tienda.get(url).status_code, (302, 403), url)
        # El operario sin PROCESOS_FABRICACION no puede avanzar órdenes
        obrero = self.login("obrero_f")
        self.assertIn(obrero.post("/fabricacion/ordenes/1/avanzar").status_code, (302, 403))
        self.assertIn(obrero.get("/fabricacion/costos").status_code, (302, 403))

    # ------------------------------------------------------------ restaurante
    def test_restaurant_end_to_end_and_isolation(self):
        c = self.login("ger_r")
        u_r1 = self.ids["r1"][1]
        self.post(c, "/restaurante/insumos/nuevo", nombre="Carne", unidad_medida="kg", stock_minimo="1")
        with app.app_context():
            carne = Insumo.query.filter_by(unidad_negocio_id=u_r1, nombre="Carne").one()
            carne_id = carne.id
        self.post(c, "/restaurante/compras/nueva", insumo_id=carne_id, cantidad="10", costo_total="1000")
        self.post(c, "/restaurante/menu/nuevo", nombre="Hamburguesa", categoria="PLATILLO", precio="150")
        with app.app_context():
            plat_id = Platillo.query.filter_by(unidad_negocio_id=u_r1).one().id
        self.post(c, f"/restaurante/recetas/{plat_id}/agregar", insumo_id=carne_id, cantidad="0.2")
        self.post(c, "/restaurante/mesas/nueva", nombre="M1")
        with app.app_context():
            mesa_id = Mesa.query.filter_by(unidad_negocio_id=u_r1).one().id
        r = self.post(c, "/restaurante/pedidos/nuevo", tipo="SALON", mesa_id=mesa_id)
        with app.app_context():
            ped = Pedido.query.filter_by(unidad_negocio_id=u_r1).one()
            ped_id, folio = ped.id, ped.folio
        # Una mesa no admite dos pedidos abiertos
        self.post(c, "/restaurante/pedidos/nuevo", tipo="SALON", mesa_id=mesa_id)
        with app.app_context():
            self.assertEqual(Pedido.query.filter_by(unidad_negocio_id=u_r1).count(), 1)
        # Existencia insuficiente bloquea el envío a cocina
        self.post(c, f"/restaurante/pedidos/{ped_id}/agregar", platillo_id=plat_id, cantidad="100")
        self.post(c, f"/restaurante/pedidos/{ped_id}/enviar")
        with app.app_context():
            self.assertAlmostEqual(Insumo.query.get(carne_id).existencia, 10)
            det = Pedido.query.get(ped_id).detalles[0]
            self.assertFalse(det.enviado)
            det_id = det.id
        self.post(c, f"/restaurante/pedidos/{ped_id}/quitar/{det_id}")
        self.post(c, f"/restaurante/pedidos/{ped_id}/agregar", platillo_id=plat_id, cantidad="2")
        self.post(c, f"/restaurante/pedidos/{ped_id}/enviar")
        with app.app_context():
            self.assertAlmostEqual(Insumo.query.get(carne_id).existencia, 9.6)
            det_id = Pedido.query.get(ped_id).detalles[0].id
        cocina = self.login("ger_r")
        self.assertIn("Hamburguesa", cocina.get("/restaurante/cocina").get_data(as_text=True))
        self.post(cocina, f"/restaurante/cocina/{det_id}/LISTO")
        self.post(c, f"/restaurante/pedidos/{ped_id}/cobrar", metodo_pago="EFECTIVO", propina="10")
        with app.app_context():
            p = Pedido.query.get(ped_id)
            self.assertEqual((p.estado, p.total, p.propina), ("PAGADO", 300, 10))
            self.assertAlmostEqual(Caja.query.filter_by(unidad_negocio_id=u_r1).one().saldo_actual, 410)
        # Cobro doble rechazado
        self.post(c, f"/restaurante/pedidos/{ped_id}/cobrar", metodo_pago="EFECTIVO")
        with app.app_context():
            self.assertAlmostEqual(Caja.query.filter_by(unidad_negocio_id=u_r1).one().saldo_actual, 410)
        # Merma de 1 kg (costo 100)
        self.post(c, "/restaurante/mermas/nueva", insumo_id=carne_id, cantidad="1", motivo="caducidad")
        html = c.get("/restaurante/reportes").get_data(as_text=True)
        self.assertIn("$300.00", html)   # ventas
        self.assertIn("$40.00", html)    # costo platillos
        self.assertIn("$160.00", html)   # 300 - 40 - 100 merma
        # Aislamiento: otra empresa no ve ni toca datos de r1
        otro = self.login("ger_r2")
        self.assertNotIn("Hamburguesa", otro.get("/restaurante/menu").get_data(as_text=True))
        self.assertEqual(otro.get(f"/restaurante/pedidos/{ped_id}").status_code, 403)
        self.assertEqual(self.post(otro, f"/restaurante/pedidos/{ped_id}/cancelar").status_code, 403)
        self.assertEqual(otro.get(f"/restaurante/recetas/{plat_id}").status_code, 403)
        self.assertEqual(self.post(otro, "/restaurante/mermas/nueva", insumo_id=carne_id, cantidad="1").status_code, 403)
        self.assertEqual(otro.get(f"/restaurante/pedidos?unidad_id={u_r1}").status_code, 403)
        self.assertIn("$0.00", otro.get("/restaurante/reportes").get_data(as_text=True))
        # El administrador principal elige unidad y ve el consolidado
        p = self.login("principal_g")
        self.assertEqual(p.get("/restaurante/pedidos").status_code, 200)
        self.assertIn("$300.00", p.get("/restaurante/reportes?unidad_id=todas").get_data(as_text=True))

    # ------------------------------------------------------------ fabricación
    def test_manufacturing_end_to_end(self):
        c = self.login("ger_f")
        e_f, u_f = self.ids["f1"]
        self.post(c, "/fabricacion/insumos/nuevo", nombre="Tela", unidad_medida="m")
        with app.app_context():
            tela = Insumo.query.filter_by(unidad_negocio_id=u_f, nombre="Tela").one().id
            prod = Producto(unidad_negocio_id=u_f, codigo="F-ALM", nombre="Almohada", precio=200)
            db.session.add(prod)
            db.session.commit()
            prod_id = prod.id
        self.post(c, "/fabricacion/compras/nueva", insumo_id=tela, cantidad="100", costo_total="1000")
        self.post(c, f"/fabricacion/recetas/{prod_id}/agregar", insumo_id=tela, cantidad="2")
        self.post(c, "/fabricacion/ordenes/nueva", producto_id=prod_id, cantidad="10")
        with app.app_context():
            o = OrdenProduccion.query.filter_by(producto_id=prod_id).one()
            oid = o.id
        # No se puede terminar antes de tiempo
        self.post(c, f"/fabricacion/ordenes/{oid}/terminar", cantidad_producida="10")
        with app.app_context():
            self.assertEqual(OrdenProduccion.query.get(oid).estado, "PLANIFICADA")
        for _ in range(5):
            self.post(c, f"/fabricacion/ordenes/{oid}/avanzar")
        with app.app_context():
            o = OrdenProduccion.query.get(oid)
            self.assertEqual(o.estado, "ACABADO")
            self.assertAlmostEqual(o.costo_materiales, 200)  # 20 m x $10
            self.assertAlmostEqual(Insumo.query.get(tela).existencia, 80)
        self.post(c, f"/fabricacion/ordenes/{oid}/terminar", cantidad_producida="9", mano_obra="90")
        with app.app_context():
            o = OrdenProduccion.query.get(oid)
            self.assertEqual(o.estado, "TERMINADA")
            self.assertAlmostEqual(o.costo_desperdicio, 20)
            self.assertAlmostEqual(o.costo_unitario, (200 + 90) / 9, places=3)
            self.assertEqual(stock_producto(prod_id, u_f), 9)
        self.assertIn("Almohada", c.get("/fabricacion/costos").get_data(as_text=True))
        # Otra empresa no puede acceder a la orden
        otro = self.login("ger_t")
        self.assertIn(otro.get(f"/fabricacion/ordenes/{oid}").status_code, (302, 403))

    def test_cannot_consume_more_than_available(self):
        c = self.login("ger_f")
        u_f = self.ids["f1"][1]
        self.post(c, "/fabricacion/insumos/nuevo", nombre="Hilo", unidad_medida="rollo")
        with app.app_context():
            hilo = Insumo.query.filter_by(unidad_negocio_id=u_f, nombre="Hilo").one().id
            prod = Producto(unidad_negocio_id=u_f, codigo="F-CORT", nombre="Cortina", precio=500)
            db.session.add(prod)
            db.session.commit()
            prod_id = prod.id
        self.post(c, f"/fabricacion/recetas/{prod_id}/agregar", insumo_id=hilo, cantidad="3")
        self.post(c, "/fabricacion/ordenes/nueva", producto_id=prod_id, cantidad="1")
        with app.app_context():
            oid = OrdenProduccion.query.filter_by(producto_id=prod_id).one().id
        self.post(c, f"/fabricacion/ordenes/{oid}/avanzar")
        with app.app_context():
            self.assertEqual(OrdenProduccion.query.get(oid).estado, "PLANIFICADA")
            self.assertEqual(Insumo.query.get(hilo).existencia, 0)


if __name__ == "__main__":
    unittest.main()
