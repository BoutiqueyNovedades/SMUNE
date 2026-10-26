"""Módulos especializados por giro: restaurante y fabricación textil.

Todos los registros pertenecen a una unidad de negocio. Cada ruta valida el
módulo requerido y el alcance de la unidad del usuario en el servidor.
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from flask import abort, flash, make_response, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

ESTADOS_ORDEN = ["PLANIFICADA", "CORTE", "CONFECCION", "RELLENO", "ENSAMBLE", "ACABADO", "TERMINADA"]
AREAS = {
    "RESTAURANTE": {"MENU", "RECETAS_RESTAURANTE", "PEDIDOS", "COCINA", "MERMA_RESTAURANTE"},
    "FABRICACION": {
        "MATERIAS_PRIMAS", "RECETAS_FABRICACION", "ORDENES_PRODUCCION",
        "PROCESOS_FABRICACION", "COSTOS_FABRICACION",
    },
}
METODOS_PAGO = ("EFECTIVO", "TARJETA", "TRANSFERENCIA")


def crear_modelos(db):
    FK_UNIDAD = lambda: db.Column(db.Integer, db.ForeignKey("unidad_negocio.id"), nullable=False, index=True)

    class Insumo(db.Model):
        __tablename__ = "insumo"
        id = db.Column(db.Integer, primary_key=True)
        unidad_negocio_id = FK_UNIDAD()
        ambito = db.Column(db.String(20), nullable=False)
        nombre = db.Column(db.String(150), nullable=False)
        unidad_medida = db.Column(db.String(20), default="pza")
        existencia = db.Column(db.Float, default=0)
        costo_promedio = db.Column(db.Float, default=0)
        stock_minimo = db.Column(db.Float, default=0)
        activo = db.Column(db.Boolean, default=True)

    class MovimientoInsumo(db.Model):
        __tablename__ = "movimiento_insumo"
        id = db.Column(db.Integer, primary_key=True)
        insumo_id = db.Column(db.Integer, db.ForeignKey("insumo.id"), nullable=False)
        unidad_negocio_id = FK_UNIDAD()
        fecha = db.Column(db.DateTime, default=datetime.now)
        tipo = db.Column(db.String(30))
        cantidad = db.Column(db.Float)
        costo_unitario = db.Column(db.Float, default=0)
        referencia = db.Column(db.String(60))
        observaciones = db.Column(db.String(300))
        usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
        proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedor.id"))
        insumo = db.relationship("Insumo")
        proveedor = db.relationship("Proveedor")

    class Platillo(db.Model):
        __tablename__ = "platillo"
        id = db.Column(db.Integer, primary_key=True)
        unidad_negocio_id = FK_UNIDAD()
        nombre = db.Column(db.String(150), nullable=False)
        categoria = db.Column(db.String(30), default="PLATILLO")
        precio = db.Column(db.Float, default=0)
        activo = db.Column(db.Boolean, default=True)

    class RecetaPlatillo(db.Model):
        __tablename__ = "receta_platillo"
        id = db.Column(db.Integer, primary_key=True)
        platillo_id = db.Column(db.Integer, db.ForeignKey("platillo.id"), nullable=False)
        insumo_id = db.Column(db.Integer, db.ForeignKey("insumo.id"), nullable=False)
        cantidad = db.Column(db.Float, nullable=False)
        insumo = db.relationship("Insumo")

    class Mesa(db.Model):
        __tablename__ = "mesa"
        id = db.Column(db.Integer, primary_key=True)
        unidad_negocio_id = FK_UNIDAD()
        nombre = db.Column(db.String(60), nullable=False)
        activa = db.Column(db.Boolean, default=True)

    class Pedido(db.Model):
        __tablename__ = "pedido_restaurante"
        id = db.Column(db.Integer, primary_key=True)
        unidad_negocio_id = FK_UNIDAD()
        folio = db.Column(db.String(30), unique=True)
        tipo = db.Column(db.String(20), default="SALON")
        mesa_id = db.Column(db.Integer, db.ForeignKey("mesa.id"))
        cliente_nombre = db.Column(db.String(150))
        telefono = db.Column(db.String(30))
        direccion = db.Column(db.String(250))
        estado = db.Column(db.String(20), default="ABIERTO")
        total = db.Column(db.Float, default=0)
        propina = db.Column(db.Float, default=0)
        metodo_pago = db.Column(db.String(20))
        fecha = db.Column(db.DateTime, default=datetime.now)
        fecha_pago = db.Column(db.DateTime)
        usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
        mesa = db.relationship("Mesa")
        usuario = db.relationship("Usuario")
        detalles = db.relationship("PedidoDetalle", backref="pedido", order_by="PedidoDetalle.id")

    class PedidoDetalle(db.Model):
        __tablename__ = "pedido_detalle"
        id = db.Column(db.Integer, primary_key=True)
        pedido_id = db.Column(db.Integer, db.ForeignKey("pedido_restaurante.id"), nullable=False)
        platillo_id = db.Column(db.Integer, db.ForeignKey("platillo.id"), nullable=False)
        nombre = db.Column(db.String(150))
        cantidad = db.Column(db.Integer, default=1)
        precio = db.Column(db.Float, default=0)
        costo_unitario = db.Column(db.Float, default=0)
        nota = db.Column(db.String(200))
        enviado = db.Column(db.Boolean, default=False)
        estado_cocina = db.Column(db.String(20), default="PENDIENTE")

    class ListaMaterial(db.Model):
        __tablename__ = "lista_material"
        id = db.Column(db.Integer, primary_key=True)
        producto_id = db.Column(db.Integer, db.ForeignKey("producto.id"), nullable=False)
        insumo_id = db.Column(db.Integer, db.ForeignKey("insumo.id"), nullable=False)
        cantidad = db.Column(db.Float, nullable=False)
        insumo = db.relationship("Insumo")

    class OrdenProduccion(db.Model):
        __tablename__ = "orden_produccion"
        id = db.Column(db.Integer, primary_key=True)
        unidad_negocio_id = FK_UNIDAD()
        folio = db.Column(db.String(30), unique=True)
        producto_id = db.Column(db.Integer, db.ForeignKey("producto.id"), nullable=False)
        cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"))
        cantidad = db.Column(db.Integer, nullable=False)
        cantidad_producida = db.Column(db.Integer, default=0)
        estado = db.Column(db.String(20), default="PLANIFICADA")
        notas = db.Column(db.String(300))
        fecha_entrega = db.Column(db.Date)
        fecha = db.Column(db.DateTime, default=datetime.now)
        fecha_fin = db.Column(db.DateTime)
        usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
        costo_materiales = db.Column(db.Float, default=0)
        mano_obra = db.Column(db.Float, default=0)
        costo_desperdicio = db.Column(db.Float, default=0)
        costo_unitario = db.Column(db.Float, default=0)
        producto = db.relationship("Producto")
        cliente = db.relationship("Cliente")

    return SimpleNamespace(**{c.__name__: c for c in (
        Insumo, MovimientoInsumo, Platillo, RecetaPlatillo, Mesa, Pedido,
        PedidoDetalle, ListaMaterial, OrdenProduccion,
    )})


def registrar(app, db, M, D):
    """D aporta las dependencias de app.py (cajas, inventario, permisos...)."""

    def ruta(url, endpoint, modulo, methods=("GET",)):
        def deco(f):
            app.add_url_rule(
                url, endpoint, login_required(D.modulo_requerido(modulo)(f)), methods=list(methods)
            )
            return f
        return deco

    # ------------------------------------------------------------ alcance
    def visibles(area):
        q = D.UnidadNegocio.query.filter_by(activa=True)
        if current_user.administrador_principal:
            pass
        elif current_user.unidad_negocio_id:
            q = q.filter(D.UnidadNegocio.id == current_user.unidad_negocio_id)
        elif current_user.empresa_id:
            q = q.filter(D.UnidadNegocio.empresa_id == current_user.empresa_id)
        else:
            return []
        return [
            u for u in q.order_by(D.UnidadNegocio.nombre)
            if u.empresa.activa and D.modulos_habilitados_empresa(u.empresa) & AREAS[area]
        ]

    def trabajo(area):
        vis = visibles(area)
        if not vis:
            abort(403)
        por_id = {u.id: u for u in vis}
        uid = request.values.get("unidad_id", type=int)
        if uid is None and request.values.get("unidad_id") == "todas" and request.method == "GET":
            return vis[0], vis
        if uid is not None:
            if uid not in por_id:
                abort(403)
            session[f"unidad_{area}"] = uid
        else:
            uid = session.get(f"unidad_{area}")
            if uid not in por_id:
                uid = vis[0].id if len(vis) == 1 else None
        if uid is None:
            abort(make_response(render_template("giro_elegir_unidad.html", unidades=vis)))
        return por_id[uid], vis

    def vista(plantilla, unidad, vis, **ctx):
        return render_template(
            plantilla, unidad=unidad, unidades_sel=vis if len(vis) > 1 else [], **ctx
        )

    def propio(registro, unidad):
        if registro is None or registro.unidad_negocio_id != unidad.id:
            abort(403)
        return registro

    def numero(nombre, minimo=None, estricto=False, entero=False):
        try:
            valor = float(str(request.form.get(nombre, "")).replace(",", "."))
        except ValueError:
            raise ValueError(f"Valor inválido en '{nombre}'.")
        if entero:
            if valor != int(valor):
                raise ValueError(f"'{nombre}' debe ser entero.")
            valor = int(valor)
        if minimo is not None and (valor <= minimo if estricto else valor < minimo):
            raise ValueError(f"'{nombre}' debe ser {'mayor que' if estricto else 'al menos'} {minimo}.")
        return valor

    def rango_fechas():
        hoy = date.today()
        try:
            desde = datetime.strptime(request.args.get("desde", ""), "%Y-%m-%d").date()
        except ValueError:
            desde = hoy - timedelta(days=30)
        try:
            hasta = datetime.strptime(request.args.get("hasta", ""), "%Y-%m-%d").date()
        except ValueError:
            hasta = hoy
        return desde, hasta, datetime.combine(desde, datetime.min.time()), datetime.combine(
            hasta, datetime.max.time()
        )

    def ids_reporte(unidad, vis):
        if request.args.get("unidad_id") == "todas":
            return [u.id for u in vis], True
        return [unidad.id], False

    def fallo(error, destino, **kw):
        db.session.rollback()
        flash(str(error), "danger")
        return redirect(url_for(destino, **kw))

    def mover_insumo(insumo, cantidad, tipo, referencia="", obs="", costo=None, proveedor_id=None):
        nueva = round(insumo.existencia + cantidad, 6)
        if nueva < 0:
            raise ValueError(
                f"Existencia insuficiente de {insumo.nombre} "
                f"({insumo.existencia:g} {insumo.unidad_medida} disponibles)."
            )
        if cantidad > 0 and costo is not None:
            base = max(insumo.existencia, 0)
            insumo.costo_promedio = (base * insumo.costo_promedio + cantidad * costo) / (base + cantidad)
        insumo.existencia = nueva
        db.session.add(M.MovimientoInsumo(
            insumo_id=insumo.id, unidad_negocio_id=insumo.unidad_negocio_id, tipo=tipo,
            cantidad=cantidad,
            costo_unitario=costo if costo is not None else insumo.costo_promedio,
            referencia=referencia, observaciones=obs, usuario_id=current_user.id,
            proveedor_id=proveedor_id,
        ))

    # -------------------------------------------- insumos (compartido)
    def rutas_insumos(area, pref, url, mod_cat, mod_merma):
        def insumos_listado():
            u, vis = trabajo(area)
            items = M.Insumo.query.filter_by(unidad_negocio_id=u.id, ambito=area).order_by(M.Insumo.nombre).all()
            return vista("giro_insumos.html", u, vis, pref=pref, area=area, insumos=items)

        def insumo_nuevo():
            u, vis = trabajo(area)
            try:
                nombre = request.form.get("nombre", "").strip()
                if not nombre:
                    raise ValueError("El nombre es obligatorio.")
                if M.Insumo.query.filter_by(unidad_negocio_id=u.id, ambito=area, nombre=nombre).first():
                    raise ValueError("Ya existe un insumo con ese nombre.")
                db.session.add(M.Insumo(
                    unidad_negocio_id=u.id, ambito=area, nombre=nombre,
                    unidad_medida=request.form.get("unidad_medida", "pza").strip() or "pza",
                    stock_minimo=numero("stock_minimo", 0) if request.form.get("stock_minimo") else 0,
                ))
                D.registrar_auditoria(area, "NUEVO_INSUMO", nombre)
                db.session.commit()
                flash("Insumo registrado.", "success")
            except ValueError as e:
                return fallo(e, f"{pref}_insumos")
            return redirect(url_for(f"{pref}_insumos"))

        def insumo_toggle(id):
            u, _ = trabajo(area)
            insumo = propio(M.Insumo.query.get(id), u)
            insumo.activo = not insumo.activo
            db.session.commit()
            return redirect(url_for(f"{pref}_insumos"))

        def compras():
            u, vis = trabajo(area)
            insumos = M.Insumo.query.filter_by(unidad_negocio_id=u.id, ambito=area, activo=True).order_by(M.Insumo.nombre).all()
            proveedores = D.Proveedor.query.filter_by(unidad_negocio_id=u.id, activo=True).order_by(D.Proveedor.nombre).all()
            ids = [i.id for i in M.Insumo.query.filter_by(unidad_negocio_id=u.id, ambito=area)]
            historial = M.MovimientoInsumo.query.filter(
                M.MovimientoInsumo.insumo_id.in_(ids or [0]), M.MovimientoInsumo.tipo == "ENTRADA_COMPRA"
            ).order_by(M.MovimientoInsumo.fecha.desc()).limit(50).all()
            return vista("giro_compras.html", u, vis, pref=pref, insumos=insumos,
                         proveedores=proveedores, historial=historial)

        def compra_nueva():
            u, _ = trabajo(area)
            try:
                insumo = propio(M.Insumo.query.get(request.form.get("insumo_id", type=int)), u)
                if insumo.ambito != area:
                    abort(403)
                cantidad = numero("cantidad", 0, True)
                costo_total = numero("costo_total", 0)
                prov_id = request.form.get("proveedor_id", type=int)
                if prov_id:
                    prov = D.Proveedor.query.get(prov_id)
                    if prov is None or prov.unidad_negocio_id != u.id:
                        abort(403)
                ref = f"REC-{datetime.now():%Y%m%d%H%M%S}"
                mover_insumo(insumo, cantidad, "ENTRADA_COMPRA", ref, "Recepción de insumos",
                             costo_total / cantidad, prov_id)
                D.registrar_auditoria(area, "RECEPCION", f"{insumo.nombre} x{cantidad:g}")
                db.session.commit()
                flash("Recepción registrada.", "success")
            except ValueError as e:
                return fallo(e, f"{pref}_compras")
            return redirect(url_for(f"{pref}_compras"))

        def mermas():
            u, vis = trabajo(area)
            insumos = M.Insumo.query.filter_by(unidad_negocio_id=u.id, ambito=area, activo=True).order_by(M.Insumo.nombre).all()
            ids = [i.id for i in M.Insumo.query.filter_by(unidad_negocio_id=u.id, ambito=area)]
            historial = M.MovimientoInsumo.query.filter(
                M.MovimientoInsumo.insumo_id.in_(ids or [0]), M.MovimientoInsumo.tipo == "MERMA"
            ).order_by(M.MovimientoInsumo.fecha.desc()).limit(50).all()
            return vista("giro_mermas.html", u, vis, pref=pref, insumos=insumos, historial=historial)

        def merma_nueva():
            u, _ = trabajo(area)
            try:
                insumo = propio(M.Insumo.query.get(request.form.get("insumo_id", type=int)), u)
                if insumo.ambito != area:
                    abort(403)
                cantidad = numero("cantidad", 0, True)
                motivo = request.form.get("motivo", "").strip() or "Sin motivo"
                mover_insumo(insumo, -cantidad, "MERMA", "MERMA", motivo)
                D.registrar_auditoria(area, "MERMA", f"{insumo.nombre} x{cantidad:g}: {motivo}")
                db.session.commit()
                flash("Merma registrada.", "success")
            except ValueError as e:
                return fallo(e, f"{pref}_mermas")
            return redirect(url_for(f"{pref}_mermas"))

        ruta(f"/{url}/insumos", f"{pref}_insumos", mod_cat)(insumos_listado)
        ruta(f"/{url}/insumos/nuevo", f"{pref}_insumo_nuevo", mod_cat, ("POST",))(insumo_nuevo)
        ruta(f"/{url}/insumos/<int:id>/estado", f"{pref}_insumo_toggle", mod_cat, ("POST",))(insumo_toggle)
        ruta(f"/{url}/compras", f"{pref}_compras", "COMPRAS")(compras)
        ruta(f"/{url}/compras/nueva", f"{pref}_compra_nueva", "COMPRAS", ("POST",))(compra_nueva)
        ruta(f"/{url}/mermas", f"{pref}_mermas", mod_merma)(mermas)
        ruta(f"/{url}/mermas/nueva", f"{pref}_merma_nueva", mod_merma, ("POST",))(merma_nueva)

    rutas_insumos("RESTAURANTE", "rest", "restaurante", "RECETAS_RESTAURANTE", "MERMA_RESTAURANTE")
    rutas_insumos("FABRICACION", "fab", "fabricacion", "MATERIAS_PRIMAS", "COSTOS_FABRICACION")

    # -------------------------------------------------- recetas (compartido)
    def costo_items(items):
        return sum(i.cantidad * i.insumo.costo_promedio for i in items)

    # =========================================================== RESTAURANTE
    A = "RESTAURANTE"

    @ruta("/restaurante/menu", "rest_menu", "MENU")
    def rest_menu():
        u, vis = trabajo(A)
        platillos = M.Platillo.query.filter_by(unidad_negocio_id=u.id).order_by(M.Platillo.categoria, M.Platillo.nombre).all()
        return vista("rest_menu.html", u, vis, platillos=platillos)

    @ruta("/restaurante/menu/nuevo", "rest_menu_nuevo", "MENU", ("POST",))
    def rest_menu_nuevo():
        u, _ = trabajo(A)
        try:
            nombre = request.form.get("nombre", "").strip()
            categoria = request.form.get("categoria", "PLATILLO")
            if not nombre:
                raise ValueError("El nombre es obligatorio.")
            if categoria not in ("PLATILLO", "BEBIDA", "EXTRA"):
                raise ValueError("Categoría inválida.")
            db.session.add(M.Platillo(unidad_negocio_id=u.id, nombre=nombre, categoria=categoria,
                                      precio=numero("precio", 0)))
            D.registrar_auditoria("MENU", "NUEVO", nombre)
            db.session.commit()
            flash("Elemento agregado al menú.", "success")
        except ValueError as e:
            return fallo(e, "rest_menu")
        return redirect(url_for("rest_menu"))

    @ruta("/restaurante/menu/<int:id>/editar", "rest_menu_editar", "MENU", ("POST",))
    def rest_menu_editar(id):
        u, _ = trabajo(A)
        p = propio(M.Platillo.query.get(id), u)
        try:
            p.precio = numero("precio", 0)
            if request.form.get("alternar"):
                p.activo = not p.activo
            db.session.commit()
        except ValueError as e:
            return fallo(e, "rest_menu")
        return redirect(url_for("rest_menu"))

    @ruta("/restaurante/recetas", "rest_recetas", "RECETAS_RESTAURANTE")
    def rest_recetas():
        u, vis = trabajo(A)
        filas = []
        for p in M.Platillo.query.filter_by(unidad_negocio_id=u.id).order_by(M.Platillo.nombre):
            items = M.RecetaPlatillo.query.filter_by(platillo_id=p.id).all()
            filas.append(dict(id=p.id, nombre=p.nombre, precio=p.precio, n=len(items), costo=costo_items(items)))
        return vista("giro_recetas.html", u, vis, filas=filas, detalle="rest_receta",
                     titulo="Recetas de platillos", col="Platillo")

    @ruta("/restaurante/recetas/<int:id>", "rest_receta", "RECETAS_RESTAURANTE")
    def rest_receta(id):
        u, vis = trabajo(A)
        p = propio(M.Platillo.query.get(id), u)
        items = M.RecetaPlatillo.query.filter_by(platillo_id=p.id).all()
        insumos = M.Insumo.query.filter_by(unidad_negocio_id=u.id, ambito=A, activo=True).order_by(M.Insumo.nombre).all()
        return vista("giro_receta.html", u, vis, nombre=p.nombre, precio=p.precio, items=items,
                     insumos=insumos, costo=costo_items(items), volver="rest_recetas",
                     agregar=url_for("rest_receta_agregar", id=p.id), quitar="rest_receta_quitar", pid=p.id)

    @ruta("/restaurante/recetas/<int:id>/agregar", "rest_receta_agregar", "RECETAS_RESTAURANTE", ("POST",))
    def rest_receta_agregar(id):
        u, _ = trabajo(A)
        p = propio(M.Platillo.query.get(id), u)
        try:
            insumo = propio(M.Insumo.query.get(request.form.get("insumo_id", type=int)), u)
            if insumo.ambito != A:
                abort(403)
            cantidad = numero("cantidad", 0, True)
            existente = M.RecetaPlatillo.query.filter_by(platillo_id=p.id, insumo_id=insumo.id).first()
            if existente:
                existente.cantidad = cantidad
            else:
                db.session.add(M.RecetaPlatillo(platillo_id=p.id, insumo_id=insumo.id, cantidad=cantidad))
            db.session.commit()
        except ValueError as e:
            return fallo(e, "rest_receta", id=id)
        return redirect(url_for("rest_receta", id=id))

    @ruta("/restaurante/recetas/<int:id>/quitar/<int:item_id>", "rest_receta_quitar", "RECETAS_RESTAURANTE", ("POST",))
    def rest_receta_quitar(id, item_id):
        u, _ = trabajo(A)
        p = propio(M.Platillo.query.get(id), u)
        item = M.RecetaPlatillo.query.get(item_id)
        if item is None or item.platillo_id != p.id:
            abort(403)
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for("rest_receta", id=id))

    # ---- pedidos
    def total_pedido(p):
        p.total = round(sum(d.cantidad * d.precio for d in p.detalles), 2)

    @ruta("/restaurante/pedidos", "rest_pedidos", "PEDIDOS")
    def rest_pedidos():
        u, vis = trabajo(A)
        mesas = M.Mesa.query.filter_by(unidad_negocio_id=u.id, activa=True).order_by(M.Mesa.nombre).all()
        pedidos = M.Pedido.query.filter_by(unidad_negocio_id=u.id).order_by(M.Pedido.fecha.desc()).limit(100).all()
        abiertos = {p.mesa_id for p in pedidos if p.estado in ("ABIERTO", "EN_COCINA", "LISTO", "ENTREGADO")}
        return vista("rest_pedidos.html", u, vis, mesas=mesas, pedidos=pedidos, ocupadas=abiertos)

    @ruta("/restaurante/mesas/nueva", "rest_mesa_nueva", "PEDIDOS", ("POST",))
    def rest_mesa_nueva():
        u, _ = trabajo(A)
        nombre = request.form.get("nombre", "").strip()
        if not nombre:
            return fallo("El nombre de la mesa es obligatorio.", "rest_pedidos")
        if M.Mesa.query.filter_by(unidad_negocio_id=u.id, nombre=nombre).first():
            return fallo("Ya existe una mesa con ese nombre.", "rest_pedidos")
        db.session.add(M.Mesa(unidad_negocio_id=u.id, nombre=nombre))
        db.session.commit()
        return redirect(url_for("rest_pedidos"))

    @ruta("/restaurante/pedidos/nuevo", "rest_pedido_nuevo", "PEDIDOS", ("POST",))
    def rest_pedido_nuevo():
        u, _ = trabajo(A)
        try:
            tipo = request.form.get("tipo", "SALON")
            if tipo not in ("SALON", "LLEVAR", "DOMICILIO"):
                raise ValueError("Tipo de pedido inválido.")
            mesa_id = None
            if tipo == "SALON":
                mesa = propio(M.Mesa.query.get(request.form.get("mesa_id", type=int)), u)
                ocupada = M.Pedido.query.filter(
                    M.Pedido.mesa_id == mesa.id,
                    M.Pedido.estado.in_(["ABIERTO", "EN_COCINA", "LISTO", "ENTREGADO"]),
                ).first()
                if ocupada:
                    raise ValueError(f"La mesa {mesa.nombre} ya tiene el pedido {ocupada.folio} abierto.")
                mesa_id = mesa.id
            elif tipo == "DOMICILIO" and not request.form.get("direccion", "").strip():
                raise ValueError("La dirección es obligatoria para entregas a domicilio.")
            p = M.Pedido(
                unidad_negocio_id=u.id, tipo=tipo, mesa_id=mesa_id, usuario_id=current_user.id,
                cliente_nombre=request.form.get("cliente_nombre", "").strip() or None,
                telefono=request.form.get("telefono", "").strip() or None,
                direccion=request.form.get("direccion", "").strip() or None,
            )
            db.session.add(p)
            db.session.flush()
            p.folio = f"PED-{p.id:06d}"
            db.session.commit()
        except ValueError as e:
            return fallo(e, "rest_pedidos")
        return redirect(url_for("rest_pedido", id=p.id))

    def cargar_pedido(id):
        u, vis = trabajo(A)
        return propio(M.Pedido.query.get(id), u), u, vis

    @ruta("/restaurante/pedidos/<int:id>", "rest_pedido", "PEDIDOS")
    def rest_pedido(id):
        p, u, vis = cargar_pedido(id)
        platillos = M.Platillo.query.filter_by(unidad_negocio_id=u.id, activo=True).order_by(M.Platillo.categoria, M.Platillo.nombre).all()
        return vista("rest_pedido.html", u, vis, p=p, platillos=platillos, metodos=METODOS_PAGO,
                     abierto=p.estado in ("ABIERTO", "EN_COCINA", "LISTO", "ENTREGADO"))

    @ruta("/restaurante/pedidos/<int:id>/agregar", "rest_pedido_agregar", "PEDIDOS", ("POST",))
    def rest_pedido_agregar(id):
        p, u, _ = cargar_pedido(id)
        try:
            if p.estado not in ("ABIERTO", "EN_COCINA", "LISTO", "ENTREGADO"):
                raise ValueError("El pedido ya está cerrado.")
            plat = propio(M.Platillo.query.get(request.form.get("platillo_id", type=int)), u)
            if not plat.activo:
                raise ValueError("El platillo no está disponible.")
            cantidad = numero("cantidad", 1, entero=True)
            db.session.add(M.PedidoDetalle(
                pedido_id=p.id, platillo_id=plat.id, nombre=plat.nombre, cantidad=cantidad,
                precio=plat.precio, nota=request.form.get("nota", "").strip()[:200] or None,
            ))
            db.session.flush()
            db.session.refresh(p)
            total_pedido(p)
            db.session.commit()
        except ValueError as e:
            return fallo(e, "rest_pedido", id=id)
        return redirect(url_for("rest_pedido", id=id))

    @ruta("/restaurante/pedidos/<int:id>/quitar/<int:det_id>", "rest_pedido_quitar", "PEDIDOS", ("POST",))
    def rest_pedido_quitar(id, det_id):
        p, _, _ = cargar_pedido(id)
        d = M.PedidoDetalle.query.get(det_id)
        if d is None or d.pedido_id != p.id:
            abort(403)
        if d.enviado:
            return fallo("Un artículo enviado a cocina no puede quitarse; cancele el pedido.", "rest_pedido", id=id)
        db.session.delete(d)
        db.session.flush()
        db.session.refresh(p)
        total_pedido(p)
        db.session.commit()
        return redirect(url_for("rest_pedido", id=id))

    def enviar_pendientes(p):
        nuevos = [d for d in p.detalles if not d.enviado]
        if not nuevos:
            raise ValueError("No hay artículos nuevos por enviar a cocina.")
        for d in nuevos:
            items = M.RecetaPlatillo.query.filter_by(platillo_id=d.platillo_id).all()
            d.costo_unitario = costo_items(items)
            for it in items:
                mover_insumo(it.insumo, -it.cantidad * d.cantidad, "CONSUMO", p.folio, f"Pedido {p.folio}: {d.nombre}")
            d.enviado = True
            d.estado_cocina = "PENDIENTE"
        p.estado = "EN_COCINA"

    @ruta("/restaurante/pedidos/<int:id>/enviar", "rest_pedido_enviar", "PEDIDOS", ("POST",))
    def rest_pedido_enviar(id):
        p, _, _ = cargar_pedido(id)
        try:
            if p.estado not in ("ABIERTO", "EN_COCINA", "LISTO", "ENTREGADO"):
                raise ValueError("El pedido ya está cerrado.")
            enviar_pendientes(p)
            db.session.commit()
            flash("Enviado a cocina.", "success")
        except ValueError as e:
            return fallo(e, "rest_pedido", id=id)
        return redirect(url_for("rest_pedido", id=id))

    @ruta("/restaurante/pedidos/<int:id>/entregar", "rest_pedido_entregar", "PEDIDOS", ("POST",))
    def rest_pedido_entregar(id):
        p, _, _ = cargar_pedido(id)
        for d in p.detalles:
            if d.estado_cocina == "LISTO":
                d.estado_cocina = "ENTREGADO"
        if p.estado in ("EN_COCINA", "LISTO") and all(
            d.estado_cocina == "ENTREGADO" for d in p.detalles if d.enviado
        ) and any(d.enviado for d in p.detalles):
            p.estado = "ENTREGADO"
        db.session.commit()
        return redirect(url_for("rest_pedido", id=id))

    @ruta("/restaurante/pedidos/<int:id>/cobrar", "rest_pedido_cobrar", "PEDIDOS", ("POST",))
    def rest_pedido_cobrar(id):
        p, u, _ = cargar_pedido(id)
        try:
            if p.estado not in ("ABIERTO", "EN_COCINA", "LISTO", "ENTREGADO"):
                raise ValueError("El pedido ya está cerrado.")
            if not p.detalles:
                raise ValueError("El pedido no tiene artículos.")
            metodo = request.form.get("metodo_pago", "EFECTIVO")
            if metodo not in METODOS_PAGO:
                raise ValueError("Método de pago inválido.")
            propina = numero("propina", 0) if request.form.get("propina") else 0.0
            caja = D.Caja.query.filter_by(unidad_negocio_id=u.id, abierta=True).first()
            if not caja:
                raise ValueError("Debe abrir la caja antes de cobrar.")
            if any(not d.enviado for d in p.detalles):
                enviar_pendientes(p)
            total_pedido(p)
            p.estado, p.metodo_pago, p.propina, p.fecha_pago = "PAGADO", metodo, propina, datetime.now()
            db.session.add(D.MovimientoCaja(
                caja_id=caja.id, tipo="VENTA_PEDIDO", origen_id=p.id, monto=p.total,
                usuario_id=current_user.id, observaciones=f"{p.folio} {metodo}",
            ))
            if propina > 0:
                db.session.add(D.MovimientoCaja(
                    caja_id=caja.id, tipo="PROPINA", origen_id=p.id, monto=propina,
                    usuario_id=current_user.id, observaciones=f"Propina {p.folio} {metodo}",
                ))
            if metodo == "EFECTIVO":
                caja.saldo_actual = (caja.saldo_actual or 0) + p.total + propina
            D.registrar_auditoria("PEDIDOS", "COBRO", f"{p.folio} ${p.total:.2f}")
            db.session.commit()
            flash("Pedido cobrado.", "success")
        except ValueError as e:
            return fallo(e, "rest_pedido", id=id)
        return redirect(url_for("rest_pedido", id=id))

    @ruta("/restaurante/pedidos/<int:id>/cancelar", "rest_pedido_cancelar", "PEDIDOS", ("POST",))
    def rest_pedido_cancelar(id):
        p, _, _ = cargar_pedido(id)
        if p.estado not in ("ABIERTO", "EN_COCINA", "LISTO", "ENTREGADO"):
            return fallo("El pedido ya está cerrado.", "rest_pedido", id=id)
        try:
            for d in p.detalles:
                if d.enviado and d.estado_cocina == "PENDIENTE":
                    for it in M.RecetaPlatillo.query.filter_by(platillo_id=d.platillo_id):
                        mover_insumo(it.insumo, it.cantidad * d.cantidad, "DEVOLUCION", p.folio,
                                     f"Cancelación {p.folio}")
            p.estado = "CANCELADO"
            D.registrar_auditoria("PEDIDOS", "CANCELAR", p.folio)
            db.session.commit()
        except ValueError as e:
            return fallo(e, "rest_pedido", id=id)
        return redirect(url_for("rest_pedidos"))

    # ---- cocina
    @ruta("/restaurante/cocina", "rest_cocina", "COCINA")
    def rest_cocina():
        u, vis = trabajo(A)
        detalles = (
            M.PedidoDetalle.query.join(M.Pedido)
            .filter(M.Pedido.unidad_negocio_id == u.id, M.Pedido.estado.in_(["EN_COCINA", "LISTO"]),
                    M.PedidoDetalle.enviado.is_(True),
                    M.PedidoDetalle.estado_cocina.in_(["PENDIENTE", "PREPARANDO"]))
            .order_by(M.Pedido.fecha, M.PedidoDetalle.id).all()
        )
        return vista("rest_cocina.html", u, vis, detalles=detalles)

    @ruta("/restaurante/cocina/<int:det_id>/<estado>", "rest_cocina_estado", "COCINA", ("POST",))
    def rest_cocina_estado(det_id, estado):
        u, _ = trabajo(A)
        d = M.PedidoDetalle.query.get(det_id)
        if d is None or d.pedido.unidad_negocio_id != u.id:
            abort(403)
        if estado not in ("PREPARANDO", "LISTO") or not d.enviado or d.pedido.estado not in ("EN_COCINA", "LISTO"):
            return fallo("Cambio de estado no permitido.", "rest_cocina")
        d.estado_cocina = estado
        enviados = [x for x in d.pedido.detalles if x.enviado]
        if all(x.estado_cocina in ("LISTO", "ENTREGADO") for x in enviados):
            d.pedido.estado = "LISTO"
        db.session.commit()
        return redirect(url_for("rest_cocina"))

    # ---- reportes
    @ruta("/restaurante/reportes", "rest_reportes", "REPORTES")
    def rest_reportes():
        u, vis = trabajo(A)
        ids, consolidado = ids_reporte(u, vis)
        desde, hasta, d0, d1 = rango_fechas()
        pedidos = M.Pedido.query.filter(
            M.Pedido.unidad_negocio_id.in_(ids), M.Pedido.estado == "PAGADO",
            M.Pedido.fecha_pago >= d0, M.Pedido.fecha_pago <= d1,
        ).all()
        por_platillo, por_unidad = {}, {}
        ventas = propinas = costo = 0.0
        for p in pedidos:
            ventas += p.total
            propinas += p.propina or 0
            fila_u = por_unidad.setdefault(p.unidad_negocio_id, dict(ventas=0.0, costo=0.0, pedidos=0))
            fila_u["ventas"] += p.total
            fila_u["pedidos"] += 1
            for d in p.detalles:
                c = d.cantidad * (d.costo_unitario or 0)
                costo += c
                fila_u["costo"] += c
                f = por_platillo.setdefault(d.nombre, dict(nombre=d.nombre, cantidad=0, ventas=0.0, costo=0.0))
                f["cantidad"] += d.cantidad
                f["ventas"] += d.cantidad * d.precio
                f["costo"] += c
        mermas = M.MovimientoInsumo.query.filter(
            M.MovimientoInsumo.unidad_negocio_id.in_(ids), M.MovimientoInsumo.tipo == "MERMA",
            M.MovimientoInsumo.fecha >= d0, M.MovimientoInsumo.fecha <= d1,
        ).all()
        costo_mermas = sum(-m.cantidad * (m.costo_unitario or 0) for m in mermas)
        nombres = {x.id: x.nombre for x in vis}
        unidades = [dict(nombre=nombres.get(k, k), **v, utilidad=v["ventas"] - v["costo"]) for k, v in por_unidad.items()]
        platillos = sorted(
            [dict(f, utilidad=f["ventas"] - f["costo"]) for f in por_platillo.values()],
            key=lambda f: -f["utilidad"],
        )
        return vista("rest_reportes.html", u, vis, desde=desde, hasta=hasta, consolidado=consolidado,
                     ventas=ventas, propinas=propinas, costo=costo, mermas=costo_mermas,
                     utilidad=ventas - costo - costo_mermas, pedidos=len(pedidos),
                     platillos=platillos, unidades=unidades)

    # ============================================================ FABRICACION
    F = "FABRICACION"

    @ruta("/fabricacion/recetas", "fab_recetas", "RECETAS_FABRICACION")
    def fab_recetas():
        u, vis = trabajo(F)
        filas = []
        for p in D.Producto.query.filter_by(unidad_negocio_id=u.id, activo=True).order_by(D.Producto.nombre):
            items = M.ListaMaterial.query.filter_by(producto_id=p.id).all()
            filas.append(dict(id=p.id, nombre=p.nombre, precio=p.precio, n=len(items), costo=costo_items(items)))
        return vista("giro_recetas.html", u, vis, filas=filas, detalle="fab_receta",
                     titulo="Listas de materiales", col="Producto terminado")

    @ruta("/fabricacion/recetas/<int:id>", "fab_receta", "RECETAS_FABRICACION")
    def fab_receta(id):
        u, vis = trabajo(F)
        p = propio(D.Producto.query.get(id), u)
        items = M.ListaMaterial.query.filter_by(producto_id=p.id).all()
        insumos = M.Insumo.query.filter_by(unidad_negocio_id=u.id, ambito=F, activo=True).order_by(M.Insumo.nombre).all()
        return vista("giro_receta.html", u, vis, nombre=p.nombre, precio=p.precio, items=items,
                     insumos=insumos, costo=costo_items(items), volver="fab_recetas",
                     agregar=url_for("fab_receta_agregar", id=p.id), quitar="fab_receta_quitar", pid=p.id)

    @ruta("/fabricacion/recetas/<int:id>/agregar", "fab_receta_agregar", "RECETAS_FABRICACION", ("POST",))
    def fab_receta_agregar(id):
        u, _ = trabajo(F)
        p = propio(D.Producto.query.get(id), u)
        try:
            insumo = propio(M.Insumo.query.get(request.form.get("insumo_id", type=int)), u)
            if insumo.ambito != F:
                abort(403)
            cantidad = numero("cantidad", 0, True)
            existente = M.ListaMaterial.query.filter_by(producto_id=p.id, insumo_id=insumo.id).first()
            if existente:
                existente.cantidad = cantidad
            else:
                db.session.add(M.ListaMaterial(producto_id=p.id, insumo_id=insumo.id, cantidad=cantidad))
            db.session.commit()
        except ValueError as e:
            return fallo(e, "fab_receta", id=id)
        return redirect(url_for("fab_receta", id=id))

    @ruta("/fabricacion/recetas/<int:id>/quitar/<int:item_id>", "fab_receta_quitar", "RECETAS_FABRICACION", ("POST",))
    def fab_receta_quitar(id, item_id):
        u, _ = trabajo(F)
        p = propio(D.Producto.query.get(id), u)
        item = M.ListaMaterial.query.get(item_id)
        if item is None or item.producto_id != p.id:
            abort(403)
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for("fab_receta", id=id))

    def requerimientos(orden):
        return [(m, m.cantidad * orden.cantidad) for m in M.ListaMaterial.query.filter_by(producto_id=orden.producto_id)]

    @ruta("/fabricacion/ordenes", "fab_ordenes", "ORDENES_PRODUCCION")
    def fab_ordenes():
        u, vis = trabajo(F)
        ordenes = M.OrdenProduccion.query.filter_by(unidad_negocio_id=u.id).order_by(M.OrdenProduccion.fecha.desc()).all()
        productos = [
            p for p in D.Producto.query.filter_by(unidad_negocio_id=u.id, activo=True).order_by(D.Producto.nombre)
            if M.ListaMaterial.query.filter_by(producto_id=p.id).first()
        ]
        clientes = D.Cliente.query.filter_by(unidad_negocio_id=u.id, activo=True).order_by(D.Cliente.nombre).all()
        return vista("fab_ordenes.html", u, vis, ordenes=ordenes, productos=productos, clientes=clientes)

    @ruta("/fabricacion/ordenes/nueva", "fab_orden_nueva", "ORDENES_PRODUCCION", ("POST",))
    def fab_orden_nueva():
        u, _ = trabajo(F)
        try:
            prod = propio(D.Producto.query.get(request.form.get("producto_id", type=int)), u)
            if not M.ListaMaterial.query.filter_by(producto_id=prod.id).first():
                raise ValueError("El producto no tiene lista de materiales.")
            cantidad = numero("cantidad", 0, True, entero=True)
            cliente_id = request.form.get("cliente_id", type=int)
            if cliente_id:
                propio(D.Cliente.query.get(cliente_id), u)
            entrega = None
            if request.form.get("fecha_entrega"):
                try:
                    entrega = datetime.strptime(request.form["fecha_entrega"], "%Y-%m-%d").date()
                except ValueError:
                    raise ValueError("Fecha de entrega inválida.")
            o = M.OrdenProduccion(
                unidad_negocio_id=u.id, producto_id=prod.id, cantidad=cantidad, cliente_id=cliente_id or None,
                notas=request.form.get("notas", "").strip()[:300] or None, fecha_entrega=entrega,
                usuario_id=current_user.id,
            )
            db.session.add(o)
            db.session.flush()
            o.folio = f"OP-{o.id:06d}"
            D.registrar_auditoria("ORDENES_PRODUCCION", "NUEVA", o.folio)
            db.session.commit()
        except ValueError as e:
            return fallo(e, "fab_ordenes")
        return redirect(url_for("fab_orden", id=o.id))

    @ruta("/fabricacion/ordenes/<int:id>", "fab_orden", "ORDENES_PRODUCCION")
    def fab_orden(id):
        u, vis = trabajo(F)
        o = propio(M.OrdenProduccion.query.get(id), u)
        return vista("fab_orden.html", u, vis, o=o, reqs=requerimientos(o), estados=ESTADOS_ORDEN,
                     puede_procesar=D.tiene_permiso("PROCESOS_FABRICACION"))

    @ruta("/fabricacion/ordenes/<int:id>/avanzar", "fab_orden_avanzar", "PROCESOS_FABRICACION", ("POST",))
    def fab_orden_avanzar(id):
        u, _ = trabajo(F)
        o = propio(M.OrdenProduccion.query.get(id), u)
        try:
            if o.estado not in ESTADOS_ORDEN[:5]:
                raise ValueError("La orden no puede avanzar desde su estado actual.")
            if o.estado == "PLANIFICADA":
                total = 0.0
                for m, req in requerimientos(o):
                    total += req * m.insumo.costo_promedio
                    mover_insumo(m.insumo, -req, "CONSUMO_PRODUCCION", o.folio, f"Orden {o.folio}")
                o.costo_materiales = round(total, 4)
            o.estado = ESTADOS_ORDEN[ESTADOS_ORDEN.index(o.estado) + 1]
            D.registrar_auditoria("PROCESOS_FABRICACION", "AVANZAR", f"{o.folio} -> {o.estado}")
            db.session.commit()
        except ValueError as e:
            return fallo(e, "fab_orden", id=id)
        return redirect(url_for("fab_orden", id=id))

    @ruta("/fabricacion/ordenes/<int:id>/terminar", "fab_orden_terminar", "PROCESOS_FABRICACION", ("POST",))
    def fab_orden_terminar(id):
        u, _ = trabajo(F)
        o = propio(M.OrdenProduccion.query.get(id), u)
        try:
            if o.estado != "ACABADO":
                raise ValueError("Solo se puede terminar una orden en acabado.")
            producida = numero("cantidad_producida", 0, True, entero=True)
            if producida > o.cantidad:
                raise ValueError("No puede producir más de lo planificado.")
            mano_obra = numero("mano_obra", 0) if request.form.get("mano_obra") else 0.0
            o.cantidad_producida = producida
            o.mano_obra = mano_obra
            o.costo_desperdicio = round(o.costo_materiales * (o.cantidad - producida) / o.cantidad, 4)
            o.costo_unitario = round((o.costo_materiales + mano_obra) / producida, 4)
            prod = o.producto
            previo = D.stock_producto(prod.id, u.id)
            if not D.mover_inventario(prod.id, u.id, producida, "PRODUCCION", current_user.id, o.folio,
                                      f"Producción {o.folio}"):
                raise ValueError("No fue posible actualizar el inventario.")
            prod.stock = D.stock_producto(prod.id, u.id)
            prod.costo_promedio = ((previo * (prod.costo_promedio or 0)) + producida * o.costo_unitario) / (previo + producida)
            o.estado, o.fecha_fin = "TERMINADA", datetime.now()
            D.registrar_auditoria("PROCESOS_FABRICACION", "TERMINAR", f"{o.folio} x{producida}")
            db.session.commit()
            flash("Producción terminada y enviada a inventario.", "success")
        except ValueError as e:
            return fallo(e, "fab_orden", id=id)
        return redirect(url_for("fab_orden", id=id))

    @ruta("/fabricacion/ordenes/<int:id>/cancelar", "fab_orden_cancelar", "ORDENES_PRODUCCION", ("POST",))
    def fab_orden_cancelar(id):
        u, _ = trabajo(F)
        o = propio(M.OrdenProduccion.query.get(id), u)
        if o.estado != "PLANIFICADA":
            return fallo("Solo se pueden cancelar órdenes que no han iniciado.", "fab_orden", id=id)
        o.estado = "CANCELADA"
        db.session.commit()
        return redirect(url_for("fab_ordenes"))

    @ruta("/fabricacion/costos", "fab_costos", "COSTOS_FABRICACION")
    def fab_costos():
        u, vis = trabajo(F)
        ids, consolidado = ids_reporte(u, vis)
        desde, hasta, d0, d1 = rango_fechas()
        ordenes = M.OrdenProduccion.query.filter(
            M.OrdenProduccion.unidad_negocio_id.in_(ids), M.OrdenProduccion.estado == "TERMINADA",
            M.OrdenProduccion.fecha_fin >= d0, M.OrdenProduccion.fecha_fin <= d1,
        ).order_by(M.OrdenProduccion.fecha_fin.desc()).all()
        mermas = M.MovimientoInsumo.query.join(M.Insumo).filter(
            M.MovimientoInsumo.unidad_negocio_id.in_(ids), M.MovimientoInsumo.tipo == "MERMA",
            M.Insumo.ambito == F, M.MovimientoInsumo.fecha >= d0, M.MovimientoInsumo.fecha <= d1,
        ).all()
        filas = []
        for o in ordenes:
            precio = o.producto.precio or 0
            filas.append(dict(o=o, margen=(precio - o.costo_unitario) * o.cantidad_producida))
        return vista(
            "fab_costos.html", u, vis, desde=desde, hasta=hasta, consolidado=consolidado, filas=filas,
            materiales=sum(o.costo_materiales for o in ordenes), mano_obra=sum(o.mano_obra for o in ordenes),
            desperdicio=sum(o.costo_desperdicio for o in ordenes),
            mermas=sum(-m.cantidad * (m.costo_unitario or 0) for m in mermas),
            margen=sum(f["margen"] for f in filas),
        )
