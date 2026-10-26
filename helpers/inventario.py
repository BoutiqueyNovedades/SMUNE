from app import db

def stock_producto(producto_id, unidad_id):
    from app import Inventario
    inventario = Inventario.query.filter_by(
        producto_id=producto_id,
        unidad_negocio_id=unidad_id
    ).first()
    return inventario.existencia if inventario else 0

def obtener_inventario(producto_id, unidad_id):
    from app import Inventario
    inventario = Inventario.query.filter_by(
        producto_id=producto_id,
        unidad_negocio_id=unidad_id
    ).first()
    if not inventario:
        inventario = Inventario(
            producto_id=producto_id,
            unidad_negocio_id=unidad_id,
            existencia=0
        )
        db.session.add(inventario)
        db.session.flush()
    return inventario

def aumentar_stock(producto_id, unidad_id, cantidad):
    inventario = obtener_inventario(producto_id, unidad_id)
    inventario.existencia += cantidad
    return True

def disminuir_stock(producto_id, unidad_id, cantidad):
    inventario = obtener_inventario(producto_id, unidad_id)
    if inventario.existencia < cantidad:
        return False
    inventario.existencia -= cantidad
    return True

def registrar_movimiento(producto_id, unidad_id, tipo, cantidad, usuario_id, referencia="", observaciones=""):
    from app import MovimientoInventario
    movimiento = MovimientoInventario(
        producto_id=producto_id,
        unidad_negocio_id=unidad_id,
        tipo=tipo,
        cantidad=cantidad,
        usuario_id=usuario_id,
        referencia=referencia,
        observaciones=observaciones
    )
    db.session.add(movimiento)
    return movimiento