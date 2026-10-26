"""Inicialización de acceso de sistema sin sembrar empresas ni sucursales."""

import os

from werkzeug.security import generate_password_hash


def inicializar_sistema(db, Empresa, UnidadNegocio, Usuario, Configuracion):
    """Crea únicamente el administrador principal si aún no existe.

    Las empresas y unidades se crean posteriormente desde la aplicación.
    El usuario y contraseña iniciales se pueden configurar mediante
    SMUNE_ADMIN_USER y SMUNE_ADMIN_PASSWORD.
    """
    del Empresa, UnidadNegocio, Configuracion  # Conserva compatibilidad de llamada.

    if Usuario.query.filter_by(administrador_principal=True).first():
        return None

    usuario = os.environ.get("SMUNE_ADMIN_USER", "admin").strip() or "admin"
    password = os.environ.get("SMUNE_ADMIN_PASSWORD", "Tienda00")

    if Usuario.query.filter_by(usuario=usuario).first():
        base = f"{usuario}_principal"
        usuario = base
        consecutivo = 2
        while Usuario.query.filter_by(usuario=usuario).first():
            usuario = f"{base}_{consecutivo}"
            consecutivo += 1

    administrador = Usuario(
        empresa_id=None,
        unidad_negocio_id=None,
        nombre="Administrador Principal",
        usuario=usuario,
        password=generate_password_hash(password),
        rol="ADMIN",
        activo=True,
        primer_acceso=True,
        administrador_principal=True,
    )
    db.session.add(administrador)
    db.session.commit()

    print("SMUNE listo sin empresas ni sucursales creadas.")
    print(f"Cuenta inicial del Administrador Principal: {usuario}")
    print("La contraseña inicial debe cambiarse en el primer acceso.")
    return administrador
