from app import db

def generar_folio(prefijo, modelo, campo):

    ultimo = modelo.query.order_by(
        modelo.id.desc()
    ).first()

    if not ultimo:
        return f"{prefijo}-000001"

    valor = getattr(
        ultimo,
        campo
    )

    if not valor:
        return f"{prefijo}-000001"

    numero = int(
        valor.split("-")[1]
    )

    numero += 1

    return f"{prefijo}-{numero:06d}"


def generar_numero_compra():
    from app import Compra

    return generar_folio(
        "CP",
        Compra,
        "numero_compra"
    )


def generar_numero_apartado():
    from app import Apartado

    return generar_folio(
        "AP",
        Apartado,
        "numero_apartado"
    )