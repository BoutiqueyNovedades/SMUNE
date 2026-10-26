from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user


def _empresa_habilita_modulo(empresa, codigo):
    if not empresa:
        return False
    configuracion = getattr(empresa, "modulos", ())
    if configuracion:
        return any(
            modulo.codigo == codigo and modulo.habilitado
            for modulo in configuracion
        )

    giro = (getattr(empresa, "giro", "") or "").strip().upper()
    aliases = {
        "COMERCIO MINORISTA": "TIENDA",
        "TIENDA DE ROPA": "TIENDA",
        "ROPA": "TIENDA",
        "TEXTIL": "FABRICACION",
        "FABRICA TEXTIL": "FABRICACION",
        "FABRICACIÓN": "FABRICACION",
    }
    giro = aliases.get(giro, giro)
    defaults = {
        "DASHBOARD", "PRODUCTOS", "VENTAS", "COMPRAS", "CLIENTES",
        "PROVEEDORES", "CAJA", "REPORTES", "SEGURIDAD", "CONFIGURACION",
    }
    if giro == "TIENDA":
        defaults.update({"APARTADOS", "ANALISIS_DATOS"})
    elif giro == "RESTAURANTE":
        defaults -= {"PRODUCTOS", "VENTAS", "CLIENTES"}
        defaults.update({"MENU", "RECETAS_RESTAURANTE", "PEDIDOS", "COCINA", "MERMA_RESTAURANTE"})
    elif giro == "FABRICACION":
        defaults.update({
            "MATERIAS_PRIMAS", "RECETAS_FABRICACION", "ORDENES_PRODUCCION",
            "PROCESOS_FABRICACION", "COSTOS_FABRICACION",
        })
    return codigo in defaults


def modulo_requerido(nombre_modulo):
    """
    Control de acceso por módulo.

    ADMINISTRADOR PRINCIPAL:
        Acceso universal.

    ADMIN:
        Acceso únicamente si tiene permiso asignado.

    EMPLEADO:
        Acceso únicamente si tiene permiso asignado.
    """

    def decorador(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            # -------------------------------------------------
            # USUARIO NO AUTENTICADO
            # -------------------------------------------------

            if not current_user.is_authenticated:

                flash(
                    "Debe iniciar sesión.",
                    "warning"
                )

                return redirect(
                    url_for("login")
                )

            # -------------------------------------------------
            # ADMINISTRADOR PRINCIPAL / UNIVERSAL
            # -------------------------------------------------

            if getattr(
                current_user,
                "administrador_principal",
                False
            ):

                return func(
                    *args,
                    **kwargs
                )

            empresa = getattr(current_user, "empresa", None)
            if not _empresa_habilita_modulo(empresa, nombre_modulo):
                flash(
                    "Este módulo no está habilitado para tu empresa.",
                    "warning"
                )
                return redirect(url_for("dashboard"))

            # -------------------------------------------------
            # BUSCAR PERMISOS
            # -------------------------------------------------

            permisos = getattr(current_user, "permisos", ())
            tiene_acceso = any(
                permiso.modulo == nombre_modulo and permiso.puede_ver
                for permiso in permisos
            )

            # -------------------------------------------------
            # TIENE PERMISO
            # -------------------------------------------------

            if tiene_acceso:

                return func(
                    *args,
                    **kwargs
                )

            # -------------------------------------------------
            # SIN PERMISO
            # -------------------------------------------------

            flash(
                f"No tiene permiso para acceder al módulo "
                f"'{nombre_modulo}'.",
                "danger"
            )

            return redirect(
                url_for("dashboard")
            )

        return wrapper

    return decorador