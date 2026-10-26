import os
import json
from types import SimpleNamespace
import uuid
import math
import secrets
import urllib.error
import urllib.request
from helpers.inicializacion import inicializar_sistema
from helpers.analisis_financiero import analizar_escenario
from datetime import datetime, timedelta, date
from helpers.permisos import modulo_requerido
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    session
)

from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename

from sqlalchemy import func, text
from sqlalchemy import extract
from sqlalchemy.orm import joinedload



###########################################################
# APP
###########################################################

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _clave_secreta():
    # Persistida para que las sesiones sobrevivan a los reinicios.
    clave = os.environ.get("SMUNE_SECRET_KEY")
    if clave:
        return clave
    ruta = os.path.join(BASE_DIR, ".smune_secret")
    try:
        with open(ruta, encoding="utf-8") as archivo:
            valor = archivo.read().strip()
            if valor:
                return valor
    except OSError:
        pass
    valor = secrets.token_hex(32)
    try:
        with open(ruta, "w", encoding="utf-8") as archivo:
            archivo.write(valor)
    except OSError:
        pass
    return valor


app.config["SECRET_KEY"] = _clave_secreta()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SMUNE_HTTPS") == "1"

if os.environ.get("SMUNE_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "SMUNE_DATABASE_URI",
    "sqlite:///" + os.path.join(BASE_DIR, "smune.db")
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

db = SQLAlchemy(app)

###########################################################
# MODULOS DEL SISTEMA
###########################################################

MODULOS_SISTEMA = [

    "Dashboard",

    "Productos",

    "Ventas",

    "Compras",

    "Clientes",

    "Proveedores",

    "Caja",

    "Inventario",

    "Reportes",

    "Configuracion",

    "Usuarios",

    "Empresas"

]

GIROS_EMPRESA = {
    "TIENDA": "Tienda de ropa y artículos de novedad",
    "RESTAURANTE": "Restaurante",
    "FABRICACION": "Fabricación textil y artículos para el hogar",
    "SERVICIOS": "Servicios y otros negocios",
}

GIROS_ALIASES = {
    "TIENDA DE ROPA": "TIENDA",
    "COMERCIO MINORISTA": "TIENDA",
    "ROPA": "TIENDA",
    "TEXTIL": "FABRICACION",
    "FABRICA TEXTIL": "FABRICACION",
    "FABRICACIÓN": "FABRICACION",
    "RESTAURANTE Y ALIMENTOS": "RESTAURANTE",
    "OTROS": "SERVICIOS",
}

# Only modules marked implemented are exposed as active choices. Restaurant and
# manufacturing entries are catalogued as planned, not presented as working screens.
CATALOGO_MODULOS = {
    "DASHBOARD": {"nombre": "Dashboard", "implementado": True},
    "PRODUCTOS": {"nombre": "Productos", "implementado": True},
    "VENTAS": {"nombre": "Ventas", "implementado": True},
    "COMPRAS": {"nombre": "Compras", "implementado": True},
    "CLIENTES": {"nombre": "Clientes", "implementado": True},
    "PROVEEDORES": {"nombre": "Proveedores", "implementado": True},
    "CAJA": {"nombre": "Caja", "implementado": True},
    "APARTADOS": {"nombre": "Apartados", "implementado": True},
    "REPORTES": {"nombre": "Reportes", "implementado": True},
    "ANALISIS_DATOS": {"nombre": "Análisis de datos", "implementado": True},
    "SEGURIDAD": {"nombre": "Usuarios y seguridad", "implementado": True},
    "CONFIGURACION": {"nombre": "Configuración", "implementado": True},
    "MENU": {"nombre": "Menú y modificadores", "implementado": True},
    "RECETAS_RESTAURANTE": {"nombre": "Recetas e ingredientes", "implementado": True},
    "PEDIDOS": {"nombre": "Mesas, pedidos y comandas", "implementado": True},
    "COCINA": {"nombre": "Cocina y preparación", "implementado": True},
    "MERMA_RESTAURANTE": {"nombre": "Mermas de cocina", "implementado": True},
    "MATERIAS_PRIMAS": {"nombre": "Materias primas textiles", "implementado": True},
    "RECETAS_FABRICACION": {"nombre": "Listas de materiales", "implementado": True},
    "ORDENES_PRODUCCION": {"nombre": "Órdenes de producción", "implementado": True},
    "PROCESOS_FABRICACION": {"nombre": "Corte, confección y ensamble", "implementado": True},
    "COSTOS_FABRICACION": {"nombre": "Costos y desperdicio de fabricación", "implementado": True},
}

AREAS_GIRO = {
    "RESTAURANTE": {"MENU", "RECETAS_RESTAURANTE", "PEDIDOS", "COCINA", "MERMA_RESTAURANTE"},
    "FABRICACION": {
        "MATERIAS_PRIMAS", "RECETAS_FABRICACION", "ORDENES_PRODUCCION",
        "PROCESOS_FABRICACION", "COSTOS_FABRICACION",
    },
}

MODULOS_BASE_GIRO = {
    "DASHBOARD", "PRODUCTOS", "INVENTARIO", "VENTAS", "COMPRAS", "CLIENTES",
    "PROVEEDORES", "CAJA", "REPORTES", "SEGURIDAD", "CONFIGURACION",
}


def normalizar_giro(giro):
    giro = (giro or "").strip().upper()
    return GIROS_ALIASES.get(giro, giro)


def modulos_predeterminados_por_giro(giro):
    giro = normalizar_giro(giro)
    activos = set(MODULOS_BASE_GIRO)
    if giro == "TIENDA":
        activos.update({"APARTADOS", "ANALISIS_DATOS"})
    elif giro == "RESTAURANTE":
        activos -= {"PRODUCTOS", "INVENTARIO", "VENTAS", "CLIENTES"}
        activos.update(AREAS_GIRO["RESTAURANTE"])
    elif giro == "FABRICACION":
        activos.update(AREAS_GIRO["FABRICACION"])
    return activos


def guardar_catalogo_modulos_empresa(empresa, activos):
    """Persist all module switches, including disabled/in-development modules."""
    existentes = {modulo.codigo: modulo for modulo in empresa.modulos}
    for codigo in CATALOGO_MODULOS:
        habilitado = (
            codigo in activos
            and CATALOGO_MODULOS[codigo]["implementado"]
        )
        registro = existentes.get(codigo)
        if registro is None:
            registro = EmpresaModulo(
                empresa_id=empresa.id,
                codigo=codigo,
                habilitado=habilitado,
            )
            db.session.add(registro)
        else:
            registro.habilitado = habilitado

###########################################################
# LOGIN
###########################################################
login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = "login"

login_manager.login_message = "Debes iniciar sesión."


@login_manager.user_loader
def load_user(user_id):
    try:
        usuario = db.session.get(Usuario, int(user_id))
    except (TypeError, ValueError):
        return None
    return usuario if usuario and usuario.activo else None

@app.before_request
def bloquear_cuentas_suspendidas():
    """Impide que usuarios de empresas o unidades suspendidas sigan operando."""
    if not current_user.is_authenticated:
        return None

    endpoints_permitidos_sin_cambio = {"cambiar_password", "logout", "static"}
    if (
        getattr(current_user, "primer_acceso", False)
        and request.endpoint not in endpoints_permitidos_sin_cambio
    ):
        return redirect(url_for("cambiar_password"))

    if getattr(current_user, "administrador_principal", False):
        return None

    empresa = current_user.empresa
    unidad = current_user.unidad

    if (empresa and not empresa.activa) or (unidad and not unidad.activa):
        logout_user()
        flash(
            "El acceso está suspendido para tu empresa o unidad de negocio.",
            "warning"
        )
        return redirect(url_for("login"))

    return None


def moneda(valor):
    return "${:,.2f}".format(valor or 0)


app.jinja_env.filters["moneda"] = moneda
app.jinja_env.filters["loads_json"] = json.loads

###############################################################
# CONTROL DE PERMISOS
###############################################################

def tiene_permiso(modulo):

    if not current_user.is_authenticated:
        return False

    if getattr(
        current_user,
        "administrador_principal",
        False
    ):
        return True

    empresa = getattr(current_user, "empresa", None)
    if empresa and modulo not in modulos_habilitados_empresa(empresa):
        return False

    permisos = PermisoUsuario.query.filter_by(
        usuario_id=current_user.id,
        modulo=modulo,
        puede_ver=True
    ).first()

    return permisos is not None

###########################################################
# MODELOS
###########################################################


class Empresa(db.Model):

    __tablename__ = "empresa"

    id = db.Column(db.Integer, primary_key=True)

    codigo = db.Column(
        db.String(20),
        unique=True,
        nullable=False
    )

    nombre = db.Column(
        db.String(150),
        nullable=False
    )

    giro = db.Column(
        db.String(120)
    )

    logo = db.Column(db.String(255))

    razon_social = db.Column(
        db.String(200)
    )

    rfc = db.Column(
        db.String(20)
    )

    telefono = db.Column(
        db.String(30)
    )

    correo = db.Column(
        db.String(120)
    )

    direccion = db.Column(
        db.String(250)
    )

    ciudad = db.Column(
        db.String(100)
    )

    estado = db.Column(
        db.String(100)
    )

    pais = db.Column(
        db.String(100),
        default="México"
    )

    codigo_postal = db.Column(
        db.String(10)
    )

    logo = db.Column(
        db.String(250)
    )

    activa = db.Column(
        db.Boolean,
        default=True
    )

    fecha_creacion = db.Column(
        db.DateTime,
        default=datetime.now
    )

    modulos = db.relationship(
        "EmpresaModulo",
        back_populates="empresa",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class EmpresaModulo(db.Model):
    __tablename__ = "empresa_modulo"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False,
        index=True,
    )
    codigo = db.Column(db.String(50), nullable=False)
    habilitado = db.Column(db.Boolean, default=False, nullable=False)

    empresa = db.relationship("Empresa", back_populates="modulos")

    __table_args__ = (
        db.UniqueConstraint("empresa_id", "codigo", name="uq_empresa_modulo"),
    )


class RolEmpresa(db.Model):
    __tablename__ = "rol_empresa"

    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False,
        index=True,
    )
    nombre = db.Column(db.String(60), nullable=False)
    modulos_json = db.Column(db.String(2000), nullable=False, default="[]")
    empresa = db.relationship("Empresa")

    __table_args__ = (
        db.UniqueConstraint("empresa_id", "nombre", name="uq_empresa_rol"),
    )


class UnidadNegocio(db.Model):

    __tablename__ = "unidad_negocio"

    id = db.Column(db.Integer, primary_key=True)

    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False
    )

    nombre = db.Column(
        db.String(150),
        nullable=False
    )

    direccion = db.Column(db.String(250))

    telefono = db.Column(db.String(30))

    correo = db.Column(db.String(120))

    activa = db.Column(
        db.Boolean,
        default=True
    )

    logo = db.Column(db.String(255))

    empresa = db.relationship(
        "Empresa",
        backref="unidades"
    )


class Usuario(UserMixin, db.Model):

    __tablename__ = "usuario"

    id = db.Column(db.Integer, primary_key=True)

    meses_historial_caja = db.Column(db.Integer)

    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id")
    )

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id")
    )

    nombre = db.Column(
        db.String(120),
        nullable=False
    )

    usuario = db.Column(
        db.String(60),
        unique=True,
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

    rol = db.Column(
        db.String(30),
        default="EMPLEADO"
    )

    activo = db.Column(
        db.Boolean,
        default=True
    )

    primer_acceso = db.Column(
        db.Boolean,
        default=True
    )

    administrador_principal = db.Column(
        db.Boolean,
        default=False
    )

    empresa = db.relationship(
        "Empresa"
    )

    unidad = db.relationship(
        "UnidadNegocio"
    )

###############################################################
# PERMISOS DE USUARIO
###############################################################

class PermisoUsuario(db.Model):

    __tablename__ = "permiso_usuario"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id")
    )

    modulo = db.Column(
        db.String(50)
    )

    puede_ver = db.Column(
        db.Boolean,
        default=True
    )

    usuario = db.relationship(
        "Usuario",
        backref="permisos"
    )

###########################################################
# PRODUCTOS
###########################################################


class Producto(db.Model):

    __tablename__ = "producto"

    id = db.Column(db.Integer, primary_key=True)

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False
    )

    codigo = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    codigo_barras = db.Column(
        db.String(100)
    )

    nombre = db.Column(
        db.String(200),
        nullable=False
    )

    categoria = db.Column(
        db.String(100)
    )

    talla = db.Column(
        db.String(30)
    )

    color = db.Column(
        db.String(30)
    )

    precio = db.Column(
        db.Float,
        default=0
    )

    costo_promedio = db.Column(
        db.Float,
        default=0
    )

    stock = db.Column(
        db.Integer,
        default=0
    )

    stock_minimo = db.Column(
        db.Integer,
        default=5
    )

    stock_maximo = db.Column(
        db.Integer,
        default=100
    )

    punto_reorden = db.Column(
        db.Integer,
        default=10
    )

    ubicacion = db.Column(
        db.String(100)
    )

    imagen = db.Column(
        db.String(250)
    )

    activo = db.Column(
        db.Boolean,
        default=True
    )

    unidad = db.relationship(
        "UnidadNegocio"
    )


###########################################################
# INVENTARIO POR SUCURSAL
###########################################################

class Inventario(db.Model):

    __tablename__ = "inventario"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    producto_id = db.Column(
        db.Integer,
        db.ForeignKey("producto.id"),
        nullable=False
    )

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False
    )

    existencia = db.Column(
        db.Integer,
        default=0
    )

    stock_minimo = db.Column(
        db.Integer,
        default=5
    )

    stock_maximo = db.Column(
        db.Integer,
        default=100
    )

    punto_reorden = db.Column(
        db.Integer,
        default=10
    )

    ubicacion = db.Column(
        db.String(100)
    )

    producto = db.relationship(
        "Producto",
        backref="inventarios"
    )

    unidad = db.relationship(
        "UnidadNegocio"
    )


###########################################################
# MOVIMIENTOS DE INVENTARIO
###########################################################

class MovimientoInventario(db.Model):

    __tablename__ = "movimiento_inventario"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    producto_id = db.Column(
        db.Integer,
        db.ForeignKey("producto.id"),
        nullable=False
    )

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False
    )

    tipo = db.Column(
        db.String(40),
        nullable=False
    )

    cantidad = db.Column(
        db.Integer,
        nullable=False
    )

    referencia = db.Column(
        db.String(60)
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id")
    )

    observaciones = db.Column(
        db.String(300)
    )

    producto = db.relationship(
        "Producto"
    )

    usuario = db.relationship(
        "Usuario"
    )

    unidad = db.relationship(
        "UnidadNegocio"
    )

###########################################################
# CLIENTES
###########################################################

class Cliente(db.Model):

    __tablename__ = "cliente"

    id = db.Column(db.Integer, primary_key=True)

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False
    )

    nombre = db.Column(
        db.String(150),
        nullable=False
    )

    telefono = db.Column(
        db.String(30)
    )

    correo = db.Column(
        db.String(120)
    )

    direccion = db.Column(
        db.String(250)
    )

    puntos = db.Column(
        db.Integer,
        default=0
    )

    activo = db.Column(
        db.Boolean,
        default=True
    )

    unidad = db.relationship(
        "UnidadNegocio"
    )


###########################################################
# PROVEEDORES
###########################################################

class Proveedor(db.Model):

    __tablename__ = "proveedor"

    id = db.Column(db.Integer, primary_key=True)

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id")
    )

    nombre = db.Column(
        db.String(150),
        nullable=False
    )

    telefono = db.Column(
        db.String(30)
    )

    correo = db.Column(
        db.String(120)
    )

    direccion = db.Column(
        db.String(250)
    )

    contacto = db.Column(
        db.String(120)
    )

    activo = db.Column(
        db.Boolean,
        default=True
    )


###########################################################
# CONFIGURACIÓN
###########################################################

class Configuracion(db.Model):

    __tablename__ = "configuracion"

    id = db.Column(db.Integer, primary_key=True)

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False,
        unique=True
    )

    fidelidad_activa = db.Column(
        db.Boolean,
        default=True
    )

    puntos_por_peso = db.Column(
        db.Float,
        default=1
    )

    porcentaje_fidelidad = db.Column(
        db.Float,
        default=5
    )

    mayoreo_activo = db.Column(
        db.Boolean,
        default=True
    )

    descuento_3_5 = db.Column(
        db.Float,
        default=10
    )

    descuento_6_10 = db.Column(
        db.Float,
        default=15
    )

    descuento_11_mas = db.Column(
        db.Float,
        default=20
    )

    descuento_adicional_activo = db.Column(
        db.Boolean,
        default=False
    )

    descuento_adicional_porcentaje = db.Column(
        db.Float,
        default=0
    )

    anticipo_minimo_porcentaje = db.Column(
        db.Float,
        default=20
    )

    apartados_activos = db.Column(
        db.Boolean,
        default=True
    )

    unidad = db.relationship(
        "UnidadNegocio"
    )

###########################################################
# VENTAS
###########################################################

class Venta(db.Model):

    __tablename__ = "venta"

    id = db.Column(db.Integer, primary_key=True)

    numero_venta = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    cliente_id = db.Column(
        db.Integer,
        db.ForeignKey("cliente.id")
    )

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id"),
        nullable=False
    )

    subtotal = db.Column(
        db.Float,
        default=0
    )

    descuento = db.Column(
        db.Float,
        default=0
    )

    total = db.Column(
        db.Float,
        default=0
    )

    metodo_pago = db.Column(
        db.String(30)
    )

    estado = db.Column(
        db.String(20),
        default="ACTIVA"
    )

    editada = db.Column(
        db.Boolean,
        default=False
    )

    puntos_otorgados = db.Column(
        db.Integer,
        default=0
    )

    cliente = db.relationship("Cliente")

    usuario = db.relationship("Usuario")

    unidad = db.relationship("UnidadNegocio")


class DetalleVenta(db.Model):

    __tablename__ = "detalle_venta"

    id = db.Column(db.Integer, primary_key=True)

    venta_id = db.Column(
        db.Integer,
        db.ForeignKey("venta.id"),
        nullable=False
    )

    producto_id = db.Column(
        db.Integer,
        db.ForeignKey("producto.id"),
        nullable=False
    )

    cantidad = db.Column(
        db.Integer,
        default=1
    )

    precio_unitario = db.Column(
        db.Float,
        default=0
    )

    subtotal = db.Column(
        db.Float,
        default=0
    )

    venta = db.relationship(
        "Venta",
        backref="detalles"
    )

    producto = db.relationship(
        "Producto"
    )

###########################################################
# COMPRAS
###########################################################

class Compra(db.Model):

    __tablename__ = "compra"

    id = db.Column(db.Integer, primary_key=True)

    numero_compra = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    proveedor_id = db.Column(
        db.Integer,
        db.ForeignKey("proveedor.id"),
        nullable=False
    )

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id"),
        nullable=False
    )

    total = db.Column(
        db.Float,
        default=0
    )

    proveedor = db.relationship("Proveedor")

    usuario = db.relationship("Usuario")

    unidad = db.relationship("UnidadNegocio")


class DetalleCompra(db.Model):

    __tablename__ = "detalle_compra"

    id = db.Column(db.Integer, primary_key=True)

    compra_id = db.Column(
        db.Integer,
        db.ForeignKey("compra.id"),
        nullable=False
    )

    producto_id = db.Column(
        db.Integer,
        db.ForeignKey("producto.id"),
        nullable=False
    )

    cantidad = db.Column(
        db.Integer,
        default=1
    )

    precio_unitario = db.Column(
        db.Float,
        default=0
    )

    subtotal = db.Column(
        db.Float,
        default=0
    )

    compra = db.relationship(
        "Compra",
        backref="detalles"
    )

    producto = db.relationship(
        "Producto"
    )

###########################################################
# APARTADOS
###########################################################

class Apartado(db.Model):

    __tablename__ = "apartado"

    id = db.Column(db.Integer, primary_key=True)

    numero_apartado = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    cliente_id = db.Column(
        db.Integer,
        db.ForeignKey("cliente.id"),
        nullable=False
    )

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False
    )

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    fecha_limite = db.Column(db.Date)

    fecha_entrega = db.Column(db.DateTime)

    total = db.Column(
        db.Float,
        default=0
    )

    enganche = db.Column(
        db.Float,
        default=0
    )

    saldo = db.Column(
        db.Float,
        default=0
    )

    estado = db.Column(
        db.String(20),
        default="ACTIVO"
    )

    liquidado = db.Column(
        db.Boolean,
        default=False
    )

    entregado = db.Column(
        db.Boolean,
        default=False
    )

    cancelado = db.Column(
        db.Boolean,
        default=False
    )

    puntos_otorgados = db.Column(
        db.Integer,
        default=0
    )

    observaciones = db.Column(
        db.String(300)
    )

    cliente = db.relationship("Cliente")

    unidad = db.relationship("UnidadNegocio")


class DetalleApartado(db.Model):

    __tablename__ = "detalle_apartado"

    id = db.Column(db.Integer, primary_key=True)

    apartado_id = db.Column(
        db.Integer,
        db.ForeignKey("apartado.id"),
        nullable=False
    )

    producto_id = db.Column(
        db.Integer,
        db.ForeignKey("producto.id"),
        nullable=False
    )

    cantidad = db.Column(
        db.Integer,
        default=1
    )

    precio_unitario = db.Column(
        db.Float,
        default=0
    )

    subtotal = db.Column(
        db.Float,
        default=0
    )

    apartado = db.relationship(
        "Apartado",
        backref="detalles"
    )

    producto = db.relationship("Producto")


class PagoApartado(db.Model):

    __tablename__ = "pago_apartado"

    id = db.Column(db.Integer, primary_key=True)

    apartado_id = db.Column(
        db.Integer,
        db.ForeignKey("apartado.id"),
        nullable=False
    )

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    monto = db.Column(
        db.Float,
        nullable=False
    )

    metodo_pago = db.Column(
        db.String(30),
        default="EFECTIVO"
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id")
    )

    observaciones = db.Column(
        db.String(300)
    )

    apartado = db.relationship(
        "Apartado",
        backref="pagos"
    )

    usuario = db.relationship("Usuario")


###########################################################
# CAMBIOS DE APARTADOS
###########################################################

class CambioApartado(db.Model):

    __tablename__ = "cambio_apartado"

    id = db.Column(db.Integer, primary_key=True)

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    apartado_id = db.Column(
        db.Integer,
        db.ForeignKey("apartado.id")
    )

    producto_anterior_id = db.Column(
        db.Integer,
        db.ForeignKey("producto.id")
    )

    producto_nuevo_id = db.Column(
        db.Integer,
        db.ForeignKey("producto.id")
    )

    cantidad = db.Column(db.Integer)

    precio_anterior = db.Column(db.Float)

    precio_nuevo = db.Column(db.Float)

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id")
    )


###########################################################
# CRÉDITOS
###########################################################

class CreditoCliente(db.Model):

    __tablename__ = "credito_cliente"

    id = db.Column(db.Integer, primary_key=True)

    cliente_id = db.Column(
        db.Integer,
        db.ForeignKey("cliente.id")
    )

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    tipo = db.Column(db.String(40))

    monto = db.Column(db.Float)

    saldo = db.Column(db.Float)

    origen = db.Column(db.String(50))

    observaciones = db.Column(db.String(300))

    cliente = db.relationship("Cliente")


class PagoCredito(db.Model):

    __tablename__ = "pago_credito"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"))
    fecha = db.Column(db.DateTime, default=datetime.now)
    monto = db.Column(db.Float, default=0.0)
    observaciones = db.Column(db.String(300))

    cliente = db.relationship("Cliente")


class MovimientoPuntos(db.Model):

    __tablename__ = "movimiento_puntos"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"))
    fecha = db.Column(db.DateTime, default=datetime.now)
    puntos = db.Column(db.Integer, default=0)
    tipo = db.Column(db.String(40))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
    observaciones = db.Column(db.String(300))

    usuario = db.relationship("Usuario")


###########################################################
# CAJA
###########################################################


class Caja(db.Model):
    __tablename__ = "caja"

    id = db.Column(db.Integer, primary_key=True)

    unidad_negocio_id = db.Column(
        db.Integer,
        db.ForeignKey("unidad_negocio.id"),
        nullable=False
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id"),
        nullable=False
    )

    fondo_inicial = db.Column(db.Float, default=0.0)
    saldo_actual = db.Column(db.Float, default=0.0)
    efectivo_final = db.Column(db.Float, default=0.0)
    diferencia = db.Column(db.Float, default=0.0)

    abierta = db.Column(db.Boolean, default=True)

    fecha_apertura = db.Column(db.DateTime, default=datetime.now)
    fecha_cierre = db.Column(db.DateTime)

    unidad = db.relationship("UnidadNegocio")
    usuario = db.relationship("Usuario")

class MovimientoCaja(db.Model):

    __tablename__ = "movimiento_caja"

    id = db.Column(db.Integer, primary_key=True)

    caja_id = db.Column(
        db.Integer,
        db.ForeignKey("caja.id"),
        nullable=True
    )

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    tipo = db.Column(db.String(40))

    origen_id = db.Column(db.Integer)

    monto = db.Column(db.Float)

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id")
    )

    observaciones = db.Column(db.String(300))

    usuario = db.relationship("Usuario")
    caja = db.relationship("Caja", backref="movimientos")

# MODELO CAJA FIX INSERTADO - ELIMINAR DUPLICADO ORIGINAL



class Auditoria(db.Model):

    __tablename__ = "auditoria"

    id = db.Column(db.Integer, primary_key=True)

    fecha = db.Column(
        db.DateTime,
        default=datetime.now
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id")
    )

    modulo = db.Column(db.String(50))

    accion = db.Column(db.String(100))

    descripcion = db.Column(db.String(500))

    usuario = db.relationship("Usuario")

###############################################################
# FUNCIONES DE INVENTARIO
###############################################################

def obtener_inventario(producto_id, unidad_id):
    """
    Obtiene el registro de inventario de un producto en una unidad.
    Si no existe lo crea.
    """

    inventario = Inventario.query.filter_by(
        producto_id=producto_id,
        unidad_negocio_id=unidad_id
    ).first()

    if inventario is None:

        inventario = Inventario(
            producto_id=producto_id,
            unidad_negocio_id=unidad_id,
            existencia=0
        )

        db.session.add(inventario)
        db.session.flush()

    return inventario


def stock_producto(producto_id, unidad_id):

    inventario = Inventario.query.filter_by(
        producto_id=producto_id,
        unidad_negocio_id=unidad_id
    ).first()

    if inventario:
        return inventario.existencia

    return 0


def aumentar_stock(producto_id, unidad_id, cantidad):

    inventario = obtener_inventario(
        producto_id,
        unidad_id
    )

    inventario.existencia += cantidad

    return True


def disminuir_stock(producto_id, unidad_id, cantidad):

    inventario = obtener_inventario(
        producto_id,
        unidad_id
    )

    if inventario.existencia < cantidad:
        return False

    inventario.existencia -= cantidad

    return True


###############################################################
# MOVIMIENTOS DE INVENTARIO
###############################################################

def registrar_movimiento(
    producto_id,
    unidad_id,
    tipo,
    cantidad,
    usuario_id,
    referencia="",
    observaciones=""
):

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


###############################################################
# MOTOR CENTRAL DE INVENTARIO
###############################################################

ENTRADAS = {

    "COMPRA",

    "PRODUCCION",

    "DEVOLUCION_ENTRADA",

    "AJUSTE_ENTRADA",

    "TRANSFERENCIA_ENTRADA"

}

SALIDAS = {

    "VENTA",

    "APARTADO",

    "DEVOLUCION_PROVEEDOR",

    "AJUSTE_SALIDA",

    "TRANSFERENCIA_SALIDA"

}


def mover_inventario(
    producto_id,
    unidad_id,
    cantidad,
    tipo,
    usuario_id,
    referencia="",
    observaciones=""
):

    if tipo in ENTRADAS:

        aumentar_stock(
            producto_id,
            unidad_id,
            cantidad
        )

    elif tipo in SALIDAS:

        if not disminuir_stock(
            producto_id,
            unidad_id,
            cantidad
        ):
            return False

    else:

        raise ValueError(
            f"Tipo de movimiento '{tipo}' no reconocido."
        )

    registrar_movimiento(
        producto_id=producto_id,
        unidad_id=unidad_id,
        tipo=tipo,
        cantidad=cantidad,
        usuario_id=usuario_id,
        referencia=referencia,
        observaciones=observaciones
    )

    return True


###############################################################
# SINCRONIZAR STOCK GENERAL
###############################################################

def sincronizar_stock_producto(
    producto_id,
    unidad_id
):

    producto = Producto.query.get(producto_id)

    if producto:

        producto.stock = stock_producto(
            producto.id,
            unidad_id
        )

    return producto

###############################################################
# FUNCIONES AUXILIARES
###############################################################

def generar_numero_venta():

    ultimo = Venta.query.order_by(
        Venta.id.desc()
    ).first()

    if ultimo:
        numero = ultimo.id + 1
    else:
        numero = 1

    return f"V-{numero:06}"


def generar_numero_compra():

    ultimo = Compra.query.order_by(
        Compra.id.desc()
    ).first()

    if ultimo:
        numero = ultimo.id + 1
    else:
        numero = 1

    return f"C-{numero:06}"


def generar_numero_apartado():

    ultimo = Apartado.query.order_by(
        Apartado.id.desc()
    ).first()

    if ultimo:
        numero = ultimo.id + 1
    else:
        numero = 1

    return f"A-{numero:06}"


###############################################################
# APARTADOS
###############################################################

def calcular_saldo_apartado(apartado):

    total_pagado = sum(
        pago.monto
        for pago in apartado.pagos
    )

    apartado.saldo = max(
        0,
        apartado.total - total_pagado
    )

    if apartado.saldo <= 0:

        apartado.saldo = 0

        apartado.liquidado = True

        apartado.estado = "LIQUIDADO"

    else:

        apartado.liquidado = False

        if not apartado.cancelado and not apartado.entregado:

            apartado.estado = "ACTIVO"

    return apartado.saldo


###############################################################
# AUDITORÍA
###############################################################

def registrar_auditoria(
    modulo,
    accion,
    descripcion=""
):

    if not current_user.is_authenticated:
        return

    auditoria = Auditoria(

        usuario_id=current_user.id,

        modulo=modulo,

        accion=accion,

        descripcion=descripcion

    )

    db.session.add(auditoria)


###############################################################
# VALIDACIONES
###############################################################

def validar_unidad_registro(registro):

    if getattr(
        current_user,
        "administrador_principal",
        False
    ):
        return

    if (
        current_user.unidad_negocio_id is None
        and current_user.empresa_id is not None
        and getattr(registro, "unidad", None) is not None
        and registro.unidad.empresa_id == current_user.empresa_id
        and tiene_permiso("REPORTES")
    ):
        return

    if hasattr(registro, "unidad_negocio_id"):

        if (
            registro.unidad_negocio_id
            != current_user.unidad_negocio_id
        ):

            abort(403)


def filtro_unidad(query, modelo):

    if getattr(
        current_user,
        "administrador_principal",
        False
    ):
        return query

    if hasattr(modelo, "unidad_negocio_id"):

        return query.filter(
            modelo.unidad_negocio_id ==
            current_user.unidad_negocio_id
        )

    return query

###############################################################
# GENERAR CÓDIGO EMPRESA
###############################################################

def generar_codigo_empresa():

    ultimo = db.session.query(
        func.max(Empresa.id)
    ).scalar()

    if ultimo is None:
        ultimo = 0

    return f"EMP{ultimo + 1:06d}"

###############################################################
# CREACIÓN DE BASE
###############################################################

import modulos_giro

_giro = modulos_giro.crear_modelos(db)
Insumo, MovimientoInsumo, Platillo = _giro.Insumo, _giro.MovimientoInsumo, _giro.Platillo
RecetaPlatillo, Mesa, Pedido = _giro.RecetaPlatillo, _giro.Mesa, _giro.Pedido
PedidoDetalle, ListaMaterial, OrdenProduccion = (
    _giro.PedidoDetalle, _giro.ListaMaterial, _giro.OrdenProduccion
)

import sistema

_sis = sistema.crear_modelos(db)

with app.app_context():

    db.create_all()

    try:
        with db.engine.begin() as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA table_info('empresa')")
                ).fetchall()
            }
            if "codigo" not in columns:
                connection.execute(
                    text("ALTER TABLE empresa ADD COLUMN codigo VARCHAR(20)")
                )
            if "giro" not in columns:
                connection.execute(
                    text("ALTER TABLE empresa ADD COLUMN giro VARCHAR(120)")
                )
    except Exception as error:
        app.logger.warning("Company schema migration skipped: %s", error)

    try:
        with db.engine.begin() as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA table_info('proveedor')")
                ).fetchall()
            }
            if "unidad_negocio_id" not in columns:
                connection.execute(
                    text("ALTER TABLE proveedor ADD COLUMN unidad_negocio_id INTEGER")
                )
    except Exception as error:
        app.logger.warning("Supplier schema migration skipped: %s", error)

    try:
        with db.engine.begin() as connection:
            for tabla, columna, tipo in (
                ("empresa", "logo", "VARCHAR(255)"),
                ("unidad_negocio", "logo", "VARCHAR(255)"),
                ("usuario", "meses_historial_caja", "INTEGER"),
            ):
                existentes = {
                    row[1]
                    for row in connection.execute(
                        text(f"PRAGMA table_info('{tabla}')")
                    ).fetchall()
                }
                if columna not in existentes:
                    connection.execute(
                        text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
                    )
    except Exception as error:
        app.logger.warning("Logo/history schema migration skipped: %s", error)

    inicializar_sistema(
        db=db,
        Empresa=Empresa,
        UnidadNegocio=UnidadNegocio,
        Usuario=Usuario,
        Configuracion=Configuracion,
    )

###############################################################
# MÓDULOS DEL SISTEMA
###############################################################

MODULOS_SISTEMA = [
    "DASHBOARD",
    "PRODUCTOS",
    "INVENTARIO",
    "COMPRAS",
    "VENTAS",
    "CLIENTES",
    "PROVEEDORES",
    "APARTADOS",
    "CAJA",
    "REPORTES",
    "SEGURIDAD",
    "CONFIGURACION"
]

MODULOS_PERMISOS_USUARIO = [
    "DASHBOARD",
    "PRODUCTOS",
    "INVENTARIO",
    "COMPRAS",
    "VENTAS",
    "CLIENTES",
    "PROVEEDORES",
    "APARTADOS",
    "CAJA",
    "REPORTES",
    "ANALISIS_DATOS",
    "SEGURIDAD",
    "CONFIGURACION",
    "MENU",
    "RECETAS_RESTAURANTE",
    "PEDIDOS",
    "COCINA",
    "MERMA_RESTAURANTE",
    "MATERIAS_PRIMAS",
    "RECETAS_FABRICACION",
    "ORDENES_PRODUCCION",
    "PROCESOS_FABRICACION",
    "COSTOS_FABRICACION",
]

ROLES_UNIDAD = ["ADMIN", "SUPERVISOR", "EMPLEADO"]

###############################################################
# COMPROBAR PERMISO DE USUARIO
###############################################################

def usuario_puede_ver(modulo):

    # El administrador principal tiene acceso total
    if getattr(
        current_user,
        "administrador_principal",
        False
    ):
        return True

    # Un ADMIN de unidad también tendrá acceso
    # a los módulos que posteriormente le asignemos.
    permiso = PermisoUsuario.query.filter_by(
        usuario_id=current_user.id,
        modulo=modulo,
        puede_ver=True
    ).first()

    return permiso is not None

###############################################################
# SEGURIDAD - ADMINISTRADOR PRINCIPAL / UNIVERSAL
###############################################################

def es_admin_universal():

    return (
        current_user.is_authenticated
        and
        getattr(
            current_user,
            "administrador_principal",
            False
        )
    )


def puede_administrar_usuario(usuario):

    if getattr(
        current_user,
        "administrador_principal",
        False
    ):
        return not usuario.administrador_principal

    if not tiene_permiso("SEGURIDAD"):
        return False

    rol_actual = str(getattr(current_user, "rol", "")).upper()
    rol_objetivo = str(getattr(usuario, "rol", "")).upper()

    if rol_objetivo in {"ADMIN", "GERENTE_EMPRESA"} or usuario.administrador_principal:
        return False

    if current_user.unidad_negocio_id is None and current_user.empresa_id:
        return (
            current_user.empresa_id == usuario.empresa_id
            and usuario.unidad_negocio_id is not None
        )

    return (
        current_user.unidad_negocio_id is not None
        and usuario.unidad_negocio_id == current_user.unidad_negocio_id
    )


def puede_gestionar_unidad(unidad):
    if getattr(current_user, "administrador_principal", False):
        return True

    rol = str(getattr(current_user, "rol", "")).upper()
    if not tiene_permiso("SEGURIDAD"):
        return False

    if current_user.unidad_negocio_id is None and current_user.empresa_id:
        return unidad.empresa_id == current_user.empresa_id

    if current_user.unidad_negocio_id is not None:
        return unidad.id == current_user.unidad_negocio_id

    return False


def puede_administrar_empresa(empresa, modulo="CONFIGURACION"):
    if getattr(current_user, "administrador_principal", False):
        return True
    return (
        current_user.unidad_negocio_id is None
        and current_user.empresa_id == empresa.id
        and tiene_permiso(modulo)
    )


def modulos_habilitados_empresa(empresa):
    if not empresa:
        return set()
    if empresa.modulos:
        return {
            modulo.codigo for modulo in empresa.modulos
            if modulo.habilitado
        }
    # Compatibility for tenant records created before company-module settings existed.
    return modulos_predeterminados_por_giro(empresa.giro)


def unidad_asignable(unidad_id):
    unidad = UnidadNegocio.query.get_or_404(unidad_id)
    if getattr(current_user, "administrador_principal", False):
        return unidad
    if not unidad.activa or not unidad.empresa.activa:
        abort(403)
    if current_user.unidad_negocio_id is not None:
        if unidad.id != current_user.unidad_negocio_id:
            abort(403)
        return unidad
    if (
        current_user.unidad_negocio_id is None
        and current_user.empresa_id == unidad.empresa_id
        and tiene_permiso("SEGURIDAD")
    ):
        return unidad
    abort(403)


def roles_personalizados_empresa(empresa_id):
    return {
        rol.nombre: set(json.loads(rol.modulos_json or "[]"))
        for rol in RolEmpresa.query.filter_by(empresa_id=empresa_id).order_by(RolEmpresa.nombre).all()
    }


@app.context_processor
def contexto_modulos_empresa():
    habilitados = set(CATALOGO_MODULOS) if current_user.is_authenticated and getattr(
        current_user, "administrador_principal", False
    ) else modulos_habilitados_empresa(
        getattr(current_user, "empresa", None)
    ) if current_user.is_authenticated else set()
    return {
        "modulos_empresa_activos": habilitados,
        "catalogo_modulos_empresa": CATALOGO_MODULOS,
        "giros_empresa": GIROS_EMPRESA,
    }


def migrar_admin_inicial():

    admin = Usuario.query.filter_by(
        administrador_principal=True
    ).first()

    if not admin:
        return

    if (
        admin.usuario == "Admin1"
        and check_password_hash(admin.password, "Admin1")
    ):
        admin.usuario = "admin"
        admin.password = generate_password_hash("Tienda00")
        db.session.commit()

###############################################################
# LOGIN
###############################################################

@app.route("/login", methods=["GET", "POST"])
def login():

    # Si ya existe una sesión activa
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        usuario_texto = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")

        # Validación básica
        if not usuario_texto or not password:

            flash(
                "Debes ingresar usuario y contraseña.",
                "warning"
            )

            return render_template("login.html")

        # Buscar usuario
        if app.login_bloqueado():
            flash(
                "Demasiados intentos fallidos. Espera 10 minutos.",
                "danger"
            )
            return render_template("login.html"), 429

        usuario = Usuario.query.filter_by(
            usuario=usuario_texto
        ).first()

        # Usuario inexistente
        if usuario is None:

            app.login_fallo()
            flash(
                "Usuario o contraseña incorrectos.",
                "danger"
            )

            return render_template("login.html")

        # Usuario inactivo
        if not getattr(usuario, "activo", True):

            flash(
                "El usuario está inactivo. "
                "Contacta al administrador.",
                "danger"
            )

            return render_template("login.html")

        # Verificar contraseña
        if not check_password_hash(
            usuario.password,
            password
        ):

            app.login_fallo()
            flash(
                "Usuario o contraseña incorrectos.",
                "danger"
            )

            return render_template("login.html")

        app.login_ok()
        motivo = app.motivo_bloqueo(usuario)
        if motivo:
            flash(motivo, "warning")
            return render_template("login.html")

        # Crear sesión
        login_user(
            usuario,
            remember=False
        )

        # -------------------------------------------------------
        # PRIMER ACCESO
        # -------------------------------------------------------

        if getattr(
            usuario,
            "primer_acceso",
            False
        ):

            flash(
                "Por seguridad debes cambiar "
                "tu contraseña.",
                "warning"
            )

            return redirect(
                url_for("cambiar_password")
            )

        if getattr(usuario, "administrador_principal", False):
            flash("Bienvenido, Administrador Principal.", "success")
            return redirect(url_for("dashboard"))

        # -------------------------------------------------------
        # LOGIN NORMAL
        # -------------------------------------------------------

        flash(
            "Bienvenido a SMUNE.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "login.html"
    )


###############################################################
# LOGOUT
###############################################################

@app.route("/logout", methods=["GET"])
@login_required
def logout():

    logout_user()

    flash(
        "Sesión cerrada correctamente.",
        "info"
    )

    return redirect(
        url_for("login")
    )

###############################################################
# DASHBOARD
###############################################################

@app.route("/")
@app.route("/dashboard")
@login_required
def dashboard():

    return render_template(
        "dashboard.html",
        logo_url=logo_actual_url()
    )


def logo_actual_url():
    """Logotipo de la sucursal del usuario o, en su defecto, de su empresa."""
    unidad = (
        db.session.get(UnidadNegocio, current_user.unidad_negocio_id)
        if current_user.unidad_negocio_id else None
    )
    empresa = (
        unidad.empresa if unidad
        else db.session.get(Empresa, current_user.empresa_id)
        if current_user.empresa_id else None
    )
    archivo = (unidad.logo if unidad and unidad.logo else None) or (
        empresa.logo if empresa and empresa.logo else None
    )
    if not archivo:
        return None
    return url_for("static", filename="uploads/logos/" + archivo)


###############################################################
# CAMBIO DE CONTRASEÑA
###############################################################

@app.route("/cambiar_password", methods=["GET", "POST"])
@login_required
def cambiar_password():

    if request.method == "POST":

        if current_user.primer_acceso:

            nueva = request.form["password1"]
            confirmar = request.form["password2"]

        else:

            actual = request.form["actual"]

            if not check_password_hash(
                current_user.password,
                actual
            ):
                flash(
                    "La contraseña actual es incorrecta.",
                    "danger"
                )
                return redirect(
                    url_for("cambiar_password")
                )

            nueva = request.form["nueva"]
            confirmar = request.form["confirmar"]

        if nueva != confirmar:

            flash(
                "Las contraseñas no coinciden.",
                "danger"
            )

            return redirect(
                url_for("cambiar_password")
            )

        if len(nueva) < 8:
            flash(
                "La contraseña debe tener al menos 8 caracteres.",
                "warning"
            )
            return redirect(url_for("cambiar_password"))

        current_user.password = generate_password_hash(
            nueva
        )

        current_user.primer_acceso = False

        registrar_auditoria(
            "USUARIOS",
            "CAMBIO CONTRASEÑA",
            current_user.usuario
        )

        db.session.commit()

        flash(
            "Contraseña actualizada correctamente.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "cambiar_password.html"
    )


@app.route("/mi-perfil")
@login_required
def mi_perfil():
    permisos = sorted({
        permiso.modulo
        for permiso in getattr(current_user, "permisos", ())
        if permiso.puede_ver
    })
    return render_template(
        "mi_perfil.html",
        permisos=permisos,
        modulos_activos=sorted(modulos_habilitados_empresa(current_user.empresa)),
    )

###############################################################
# EMPRESAS
###############################################################
@app.route("/empresas")
@login_required
def empresas():

    if not getattr(current_user, "administrador_principal", False):
        abort(403)

    empresas = Empresa.query.order_by(Empresa.nombre).all()

    return render_template(

        "empresas.html",

        empresas=empresas,

        total_unidades=UnidadNegocio.query.count(),

        total_usuarios=Usuario.query.count(),

        total_productos=Producto.query.count()

    )

###############################################################
# NUEVA EMPRESA
###############################################################

@app.route("/empresas/nueva", methods=["GET", "POST"])
@login_required
def nueva_empresa():

    if not getattr(current_user, "administrador_principal", False):
        abort(403)

    if request.method == "POST":

        rfc = request.form.get("rfc", "").strip()
        giro = normalizar_giro(request.form.get("giro", "TIENDA"))

        if giro not in GIROS_EMPRESA:
            flash("Selecciona un giro empresarial válido.", "warning")
            return redirect(url_for("nueva_empresa"))

        if rfc:

            existe = Empresa.query.filter_by(
                rfc=rfc
            ).first()

            if existe:

                flash(
                    "Ya existe una empresa con ese RFC.",
                    "warning"
                )

                return redirect(
                    url_for("nueva_empresa")
                )

        nombre = request.form.get("nombre", "").strip()
        if not 1 <= len(nombre) <= 150:
            flash("El nombre debe tener entre 1 y 150 caracteres.", "warning")
            return redirect(url_for("nueva_empresa"))

        empresa = Empresa(

            codigo=generar_codigo_empresa(),

            nombre=nombre,

            giro=giro,

            razon_social=request.form.get("razon_social"),

            rfc=rfc,

            telefono=request.form.get("telefono"),

            correo=request.form.get("correo"),

            direccion=request.form.get("direccion"),

            ciudad=request.form.get("ciudad"),

            estado=request.form.get("estado"),

            pais=request.form.get("pais") or "México",

            codigo_postal=request.form.get("codigo_postal"),

            activa=True

        )

        try:

            db.session.add(empresa)
            db.session.flush()
            guardar_catalogo_modulos_empresa(
                empresa,
                modulos_predeterminados_por_giro(giro)
            )
            db.session.commit()

            flash(
                "Empresa creada correctamente. Ahora puedes registrar sus sucursales.",
                "success"
            )

            return redirect(
                url_for("administrar_empresa", id=empresa.id)
            )

        except Exception as e:

            db.session.rollback()

            flash(
                f"Error al crear la empresa: {e}",
                "danger"
            )

    return render_template(
        "empresa_nueva.html"
    )

###############################################################
# VALIDAR USUARIO DEL GERENTE
###############################################################


###############################################################
# EMPRESAS EDITAR
###############################################################

@app.route("/empresas/<int:id>/editar", methods=["GET","POST"])
@login_required
def editar_empresa(id):

    empresa = Empresa.query.get_or_404(id)
    if not puede_administrar_empresa(empresa):
        abort(403)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        rfc = request.form.get("rfc", "").strip()
        giro = normalizar_giro(request.form.get("giro", "TIENDA"))

        if not nombre:
            flash("El nombre comercial es obligatorio.", "warning")
            return redirect(url_for("editar_empresa", id=empresa.id))

        if giro not in GIROS_EMPRESA:
            flash("Selecciona un giro empresarial válido.", "warning")
            return redirect(url_for("editar_empresa", id=empresa.id))

        if rfc and Empresa.query.filter(
            Empresa.rfc == rfc,
            Empresa.id != empresa.id
        ).first():
            flash("Ya existe otra empresa con ese RFC.", "warning")
            return redirect(url_for("editar_empresa", id=empresa.id))

        empresa.nombre = nombre
        empresa.giro = giro
        empresa.razon_social = request.form.get("razon_social", "").strip()
        empresa.rfc = rfc or None
        empresa.telefono = request.form.get("telefono", "").strip()
        empresa.correo = request.form.get("correo", "").strip()
        empresa.direccion = request.form.get("direccion", "").strip()
        empresa.ciudad = request.form.get("ciudad", "").strip()
        empresa.estado = request.form.get("estado", "").strip()
        empresa.pais = request.form.get("pais", "").strip() or "México"
        empresa.codigo_postal = request.form.get("codigo_postal", "").strip()

        try:
            db.session.commit()
            flash("Empresa actualizada correctamente.", "success")
            return redirect(url_for("administrar_empresa", id=empresa.id))
        except Exception as e:
            db.session.rollback()
            flash(f"No se pudo actualizar la empresa: {e}", "danger")

    return render_template(
        "empresa_editar.html",
        empresa=empresa
    )

###############################################################
# EMPRESAS ESTADO
###############################################################

@app.route(
    "/empresas/<int:id>/estado",
    methods=["POST"]
)
@login_required
def estado_empresa(id):

    if not current_user.administrador_principal:
        abort(403)

    empresa = Empresa.query.get_or_404(id)

    empresa.activa = not empresa.activa

    try:
        db.session.commit()

        estado = "activada" if empresa.activa else "suspendida"

        flash(
            f"La empresa '{empresa.nombre}' fue {estado} correctamente.",
            "success"
        )
    except Exception as e:
        db.session.rollback()
        flash(
            f"No se pudo cambiar el estado de la empresa: {e}",
            "danger"
        )

    return redirect(url_for("empresas"))


def unidad_tiene_registros(unidad):
    """Solo permite borrar unidades vacías; los datos históricos se conservan."""
    if Usuario.query.filter_by(unidad_negocio_id=unidad.id).first():
        return True

    consultas = (
        Producto.query.filter_by(unidad_negocio_id=unidad.id),
        Cliente.query.filter_by(unidad_negocio_id=unidad.id),
        Venta.query.filter_by(unidad_negocio_id=unidad.id),
        Compra.query.filter_by(unidad_negocio_id=unidad.id),
        Apartado.query.filter_by(unidad_negocio_id=unidad.id),
        Caja.query.filter_by(unidad_negocio_id=unidad.id),
        MovimientoInventario.query.filter_by(unidad_negocio_id=unidad.id),
    )
    return any(consulta.first() for consulta in consultas)


def empresa_tiene_usuarios_sin_unidad(empresa):
    return Usuario.query.filter_by(
        empresa_id=empresa.id,
        unidad_negocio_id=None
    ).first() is not None


@app.route("/empresas/<int:id>/eliminar", methods=["POST"])
@login_required
def eliminar_empresa(id):
    if not getattr(current_user, "administrador_principal", False):
        abort(403)

    empresa = Empresa.query.get_or_404(id)
    unidades = UnidadNegocio.query.filter_by(empresa_id=empresa.id).all()
    nombre_empresa = empresa.nombre

    if empresa_tiene_usuarios_sin_unidad(empresa) or any(
        unidad_tiene_registros(unidad) for unidad in unidades
    ):
        flash(
            "No se puede eliminar: la empresa tiene usuarios o unidades con "
            "información asociada. Suspéndela para conservar el historial.",
            "warning"
        )
        return redirect(url_for("empresas"))

    try:
        for unidad in unidades:
            Configuracion.query.filter_by(
                unidad_negocio_id=unidad.id
            ).delete(synchronize_session=False)
            db.session.delete(unidad)
        db.session.delete(empresa)
        db.session.commit()
        flash(f"Empresa '{nombre_empresa}' eliminada.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"No se pudo eliminar la empresa: {e}", "danger")

    return redirect(url_for("empresas"))

###############################################################
# ADMINISTRAR EMPRESA
###############################################################

@app.route("/empresas/<int:id>/administrar")
@login_required
def administrar_empresa(id):

    empresa = Empresa.query.get_or_404(id)
    if not puede_administrar_empresa(empresa):
        abort(403)

    return render_template(
        "empresa_administrar.html",
        empresa=empresa,
        gerentes=Usuario.query.filter_by(
            empresa_id=empresa.id,
            rol="GERENTE_EMPRESA"
        ).order_by(Usuario.nombre).all(),
        puede_editar=puede_administrar_empresa(empresa),
    )


@app.route("/empresas/<int:id>/modulos", methods=["GET", "POST"])
@login_required
def configurar_modulos_empresa(id):
    empresa = Empresa.query.get_or_404(id)
    if not puede_administrar_empresa(empresa):
        abort(403)

    if not empresa.modulos:
        guardar_catalogo_modulos_empresa(
            empresa, modulos_predeterminados_por_giro(empresa.giro)
        )
        db.session.commit()

    if request.method == "POST":
        seleccionados = set(request.form.getlist("modulos"))
        soportados = {
            codigo for codigo, datos in CATALOGO_MODULOS.items()
            if datos["implementado"]
        }
        if "DASHBOARD" not in seleccionados or not seleccionados.issubset(soportados):
            flash("Activa Dashboard y selecciona únicamente módulos disponibles.", "warning")
            return redirect(url_for("configurar_modulos_empresa", id=empresa.id))
        guardar_catalogo_modulos_empresa(empresa, seleccionados)
        try:
            db.session.commit()
            flash("Módulos de la empresa actualizados.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"No se pudieron guardar los módulos: {e}", "danger")
        return redirect(url_for("configurar_modulos_empresa", id=empresa.id))

    activos = modulos_habilitados_empresa(empresa)
    return render_template(
        "empresa_modulos.html",
        empresa=empresa,
        catalogo=CATALOGO_MODULOS,
        activos=activos,
        puede_editar=puede_administrar_empresa(empresa),
    )


@app.route("/empresas/<int:id>/roles", methods=["GET", "POST"])
@login_required
def roles_empresa(id):
    empresa = Empresa.query.get_or_404(id)
    if not puede_administrar_empresa(empresa, "SEGURIDAD"):
        abort(403)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        if not 3 <= len(nombre) <= 60:
            flash("El nombre del rol debe tener entre 3 y 60 caracteres.", "warning")
            return redirect(url_for("roles_empresa", id=empresa.id))
        reservados = set(ROLES_UNIDAD) | {"GERENTE_EMPRESA", "ADMINISTRADOR PRINCIPAL"}
        if nombre.upper() in reservados:
            flash("Ese nombre está reservado para un rol del sistema.", "warning")
            return redirect(url_for("roles_empresa", id=empresa.id))
        if RolEmpresa.query.filter_by(empresa_id=empresa.id, nombre=nombre).first():
            flash("Ya existe un rol personalizado con ese nombre.", "warning")
            return redirect(url_for("roles_empresa", id=empresa.id))

        habilitados = modulos_habilitados_empresa(empresa)
        concedibles = habilitados & {
            codigo for codigo, datos in CATALOGO_MODULOS.items()
            if datos["implementado"]
        }
        if getattr(current_user, "administrador_principal", False):
            seleccionables = concedibles
        else:
            seleccionables = concedibles & {
                permiso.modulo for permiso in current_user.permisos
                if permiso.puede_ver
            }
        seleccionados = set(request.form.getlist("modulos"))
        if not seleccionados or not seleccionados.issubset(seleccionables):
            flash("Selecciona al menos un módulo que tengas autorizado.", "warning")
            return redirect(url_for("roles_empresa", id=empresa.id))
        try:
            db.session.add(RolEmpresa(
                empresa_id=empresa.id,
                nombre=nombre,
                modulos_json=json.dumps(sorted(seleccionados)),
            ))
            db.session.commit()
            flash(f"Rol '{nombre}' creado para las sucursales de la empresa.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"No se pudo guardar el rol: {e}", "danger")
        return redirect(url_for("roles_empresa", id=empresa.id))

    habilitados = modulos_habilitados_empresa(empresa)
    catalogo = {
        codigo: datos for codigo, datos in CATALOGO_MODULOS.items()
        if codigo in habilitados and datos["implementado"]
    }
    if not getattr(current_user, "administrador_principal", False):
        permitidos = {
            permiso.modulo for permiso in current_user.permisos
            if permiso.puede_ver
        }
        catalogo = {codigo: datos for codigo, datos in catalogo.items() if codigo in permitidos}
    roles = RolEmpresa.query.filter_by(empresa_id=empresa.id).order_by(RolEmpresa.nombre).all()
    return render_template(
        "roles_empresa.html",
        empresa=empresa,
        catalogo=catalogo,
        roles=roles,
    )


@app.route("/empresas/<int:id>/roles/<int:rol_id>/eliminar", methods=["POST"])
@login_required
def eliminar_rol_empresa(id, rol_id):
    empresa = Empresa.query.get_or_404(id)
    if not puede_administrar_empresa(empresa, "SEGURIDAD"):
        abort(403)
    rol = RolEmpresa.query.filter_by(id=rol_id, empresa_id=empresa.id).first_or_404()
    # Keep assigned role strings stable; delete only the preset for future accounts.
    db.session.delete(rol)
    db.session.commit()
    flash("Rol personalizado eliminado. Las cuentas existentes no se alteraron.", "info")
    return redirect(url_for("roles_empresa", id=empresa.id))


@app.route("/empresas/<int:id>/gerente/nuevo", methods=["GET", "POST"])
@login_required
def nuevo_gerente_empresa(id):
    if not getattr(current_user, "administrador_principal", False):
        abort(403)

    empresa = Empresa.query.get_or_404(id)
    if not empresa.activa:
        flash("No se pueden crear cuentas en una empresa suspendida.", "warning")
        return redirect(url_for("administrar_empresa", id=empresa.id))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        usuario_login = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")
        if not nombre or not usuario_login or len(password) < 8:
            flash("Completa nombre y usuario; la contraseña requiere al menos 8 caracteres.", "warning")
            return redirect(url_for("nuevo_gerente_empresa", id=empresa.id))
        if Usuario.query.filter_by(usuario=usuario_login).first():
            flash("Ese nombre de usuario ya está registrado.", "warning")
            return redirect(url_for("nuevo_gerente_empresa", id=empresa.id))

        gerente = Usuario(
            empresa_id=empresa.id,
            unidad_negocio_id=None,
            nombre=nombre,
            usuario=usuario_login,
            password=generate_password_hash(password),
            rol="GERENTE_EMPRESA",
            activo=True,
            primer_acceso=True,
            administrador_principal=False,
        )
        db.session.add(gerente)
        db.session.flush()
        modulos_gerente = set(request.form.getlist("modulos"))
        modulos_permitidos = {
            "DASHBOARD", "REPORTES", "ANALISIS_DATOS", "SEGURIDAD", "CONFIGURACION"
        }
        if not modulos_gerente.issubset(modulos_permitidos):
            db.session.rollback()
            flash("Los permisos seleccionados no son válidos.", "danger")
            return redirect(url_for("nuevo_gerente_empresa", id=empresa.id))
        modulos_gerente.update({"DASHBOARD", "REPORTES"})
        db.session.add_all([
            PermisoUsuario(usuario_id=gerente.id, modulo=modulo, puede_ver=True)
            for modulo in sorted(modulos_gerente)
        ])
        try:
            db.session.commit()
            flash("Gerente corporativo creado con acceso de consulta a esta empresa.", "success")
            return redirect(url_for("panel_corporativo_empresa", id=empresa.id))
        except Exception as e:
            db.session.rollback()
            flash(f"No se pudo crear el gerente: {e}", "danger")

    return render_template("nuevo_gerente_empresa.html", empresa=empresa)

###############################################################
# UNIDADES DE LA EMPRESA
###############################################################

@app.route("/empresas/<int:id>/unidades")
@login_required
def unidades_empresa(id):
    empresa = Empresa.query.get_or_404(id)
    if not puede_administrar_empresa(empresa, "SEGURIDAD"):
        abort(403)

    unidades = UnidadNegocio.query.filter_by(
        empresa_id=empresa.id
    ).all()

    return render_template(
        "unidades.html",
        empresa=empresa,
        unidades=unidades
    )

###############################################################
# NUEVA UNIDAD
###############################################################

@app.route(
    "/empresas/<int:empresa_id>/unidades/nueva",
    methods=["GET", "POST"]
)
@login_required
def nueva_unidad(empresa_id):
    empresa = Empresa.query.get_or_404(empresa_id)
    if not puede_administrar_empresa(empresa):
        abort(403)

    if not empresa.activa:
        flash(
            "La empresa está suspendida. Debes activarla antes de crear "
            "unidades de negocio.",
            "warning"
        )
        return redirect(url_for("empresas"))

    if request.method == "POST":

        nombre = request.form.get("nombre", "").strip()
        if not nombre:
            flash("El nombre de la unidad es obligatorio.", "warning")
            return redirect(url_for("nueva_unidad", empresa_id=empresa.id))

        unidad = UnidadNegocio(

            empresa_id=empresa.id,

            nombre=nombre,

            direccion=request.form.get("direccion"),

            telefono=request.form.get("telefono"),

            correo=request.form.get("correo"),

            activa=True

        )

        db.session.add(unidad)

        try:
            db.session.flush()
            db.session.add(Configuracion(unidad_negocio_id=unidad.id))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f"No se pudo crear la unidad: {e}", "danger")
            return redirect(url_for("nueva_unidad", empresa_id=empresa.id))

        flash(
            "Unidad creada correctamente.",
            "success"
        )

        return redirect(
            url_for(
                "unidades_empresa",
                id=empresa.id
            )
        )

    return render_template(
        "unidad_nueva.html",
        empresa=empresa
    )

###############################################################
# UNIDADES DE NEGOCIO
###############################################################

@app.route("/unidades")
@login_required
def unidades():
    if getattr(current_user, "administrador_principal", False):
        lista = UnidadNegocio.query.order_by(
            UnidadNegocio.nombre
        ).all()
    elif current_user.unidad_negocio_id is None and current_user.empresa_id:
        if not current_user.empresa_id or not tiene_permiso("SEGURIDAD"):
            abort(403)
        lista = UnidadNegocio.query.filter_by(
            empresa_id=current_user.empresa_id
        ).order_by(UnidadNegocio.nombre).all()
    else:
        unidad = UnidadNegocio.query.get(current_user.unidad_negocio_id)
        if not unidad or not puede_gestionar_unidad(unidad):
            abort(403)
        lista = UnidadNegocio.query.filter_by(
            id=unidad.id
        ).order_by(
            UnidadNegocio.nombre
        ).all()

    # ---------------------------------------------------------
    # MOSTRAR UNIDADES
    # ---------------------------------------------------------

    return render_template(
        "unidades.html",
        unidades=lista
    )

###############################################################
# ADMINISTRAR UNIDAD DE NEGOCIO
###############################################################

@app.route("/unidades/<int:id>/administrar")
@login_required
def administrar_unidad(id):
    unidad = UnidadNegocio.query.get_or_404(id)
    if not puede_gestionar_unidad(unidad) and not puede_administrar_empresa(
        Empresa.query.get_or_404(unidad.empresa_id), "CONFIGURACION"
    ):
        abort(403)

    # Buscar empresa
    empresa = Empresa.query.get_or_404(
        unidad.empresa_id
    )

    # Usuarios de esta unidad
    usuarios = Usuario.query.filter_by(
        unidad_negocio_id=unidad.id
    ).order_by(
        Usuario.nombre
    ).all()

    # Productos de esta unidad
    productos = Producto.query.filter_by(
        unidad_negocio_id=unidad.id
    ).count()

    return render_template(
        "administrar_unidad.html",

        empresa=empresa,

        unidad=unidad,

        usuarios=usuarios,

        total_productos=productos,
        puede_gestionar_usuarios=puede_gestionar_unidad(unidad),
        puede_configurar_unidad=(
            puede_administrar_empresa(empresa)
            or (
                str(getattr(current_user, "rol", "")).upper() == "ADMIN"
                and unidad.id == current_user.unidad_negocio_id
                and tiene_permiso("CONFIGURACION")
            )
        ),
    )

###############################################################
# EDITAR UNIDAD DE NEGOCIO
###############################################################

@app.route(
    "/unidades/<int:id>/editar",
    methods=["GET", "POST"]
)
@login_required
def editar_unidad(id):
    unidad = UnidadNegocio.query.get_or_404(id)
    empresa = Empresa.query.get_or_404(unidad.empresa_id)
    if not puede_administrar_empresa(empresa) and not (
        str(getattr(current_user, "rol", "")).upper() == "ADMIN"
        and unidad.id == current_user.unidad_negocio_id
        and tiene_permiso("CONFIGURACION")
    ):
        abort(403)

    if request.method == "POST":

        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        correo = request.form.get("correo", "").strip()

        if not nombre:
            flash(
                "El nombre de la unidad es obligatorio.",
                "warning"
            )
            return redirect(
                url_for("editar_unidad", id=unidad.id)
            )

        unidad.nombre = nombre
        unidad.telefono = telefono
        unidad.direccion = direccion
        unidad.correo = correo

        try:
            db.session.commit()
            flash(
                f"Unidad '{unidad.nombre}' actualizada correctamente.",
                "success"
            )
            return redirect(
                url_for("administrar_unidad", id=unidad.id)
            )
        except Exception as e:
            db.session.rollback()
            flash(
                f"Error al actualizar la unidad: {e}",
                "danger"
            )
            return redirect(
                url_for("editar_unidad", id=unidad.id)
            )

    return render_template(
        "editar_unidad.html",
        unidad=unidad,
        empresa=empresa
    )


###############################################################
# CAMBIAR ESTADO DE UNIDAD
###############################################################

@app.route(
    "/unidades/<int:id>/estado",
    methods=["POST"]
)
@login_required
def cambiar_estado_unidad(id):
    unidad = UnidadNegocio.query.get_or_404(id)
    empresa = Empresa.query.get_or_404(unidad.empresa_id)
    if not puede_administrar_empresa(empresa):
        abort(403)
    unidad.activa = not unidad.activa

    try:
        db.session.commit()
        estado = "activada" if unidad.activa else "desactivada"
        flash(
            f"La unidad '{unidad.nombre}' fue {estado} correctamente.",
            "success"
        )
    except Exception as e:
        db.session.rollback()
        flash(
            f"No se pudo cambiar el estado: {e}",
            "danger"
        )

    return redirect(
        url_for("administrar_unidad", id=unidad.id)
    )


@app.route("/unidades/<int:id>/eliminar", methods=["POST"])
@login_required
def eliminar_unidad(id):
    if not getattr(current_user, "administrador_principal", False):
        abort(403)

    unidad = UnidadNegocio.query.get_or_404(id)
    empresa_id = unidad.empresa_id

    if unidad_tiene_registros(unidad):
        flash(
            "No se puede eliminar: la unidad tiene usuarios o datos asociados. "
            "Suspéndela para conservar el historial.",
            "warning"
        )
        return redirect(url_for("administrar_unidad", id=unidad.id))

    try:
        Configuracion.query.filter_by(
            unidad_negocio_id=unidad.id
        ).delete(synchronize_session=False)
        db.session.delete(unidad)
        db.session.commit()
        flash("Unidad eliminada correctamente.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"No se pudo eliminar la unidad: {e}", "danger")

    return redirect(url_for("unidades_empresa", id=empresa_id))

###############################################################
# NUEVO USUARIO DE UNA UNIDAD
###############################################################

@app.route(
    "/unidades/<int:id>/usuarios/nuevo",
    methods=["GET", "POST"]
)
@login_required
def nuevo_usuario_unidad(id):

    # ---------------------------------------------------------
    # SOLO ADMINISTRADOR PRINCIPAL / UNIVERSAL
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # BUSCAR UNIDAD
    # ---------------------------------------------------------

    unidad = UnidadNegocio.query.get_or_404(id)

    if not puede_gestionar_unidad(unidad):
        abort(403)

    if not unidad.activa or not unidad.empresa.activa:
        abort(403)

    # ---------------------------------------------------------
    # CREAR USUARIO
    # ---------------------------------------------------------

    if request.method == "POST":

        nombre = request.form.get(
            "nombre",
            ""
        ).strip()

        usuario = request.form.get(
            "usuario",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        rol = request.form.get(
            "rol",
            "EMPLEADO"
        ).strip().upper()

        # -----------------------------------------------------
        # VALIDAR NOMBRE
        # -----------------------------------------------------

        if not nombre:

            flash(
                "El nombre del usuario es obligatorio.",
                "warning"
            )

            return redirect(
                url_for(
                    "nuevo_usuario_unidad",
                    id=unidad.id
                )
            )

        # -----------------------------------------------------
        # VALIDAR USUARIO
        # -----------------------------------------------------

        if not usuario:

            flash(
                "El nombre de usuario es obligatorio.",
                "warning"
            )

            return redirect(
                url_for(
                    "nuevo_usuario_unidad",
                    id=unidad.id
                )
            )

        # -----------------------------------------------------
        # VALIDAR CONTRASEÑA
        # -----------------------------------------------------

        if len(password) < 8:

            flash(
            "La contraseña temporal debe tener al menos 8 caracteres.",
                "warning"
            )

            return redirect(
                url_for(
                    "nuevo_usuario_unidad",
                    id=unidad.id
                )
            )

        # -----------------------------------------------------
        # VALIDAR USUARIO DUPLICADO
        # -----------------------------------------------------

        usuario_existente = Usuario.query.filter_by(
            usuario=usuario
        ).first()

        if usuario_existente:

            flash(
                "Ese nombre de usuario ya existe.",
                "warning"
            )

            return redirect(
                url_for(
                    "nuevo_usuario_unidad",
                    id=unidad.id
                )
            )

        # -----------------------------------------------------
        # VALIDAR ROL
        # -----------------------------------------------------

        roles_personalizados = roles_personalizados_empresa(unidad.empresa_id)
        roles_permitidos = set(ROLES_UNIDAD) | set(roles_personalizados)
        if getattr(current_user, "administrador_principal", False):
            roles_permitidos.add("ADMIN")

        if rol not in roles_permitidos:

            flash(
                "El rol seleccionado no es válido.",
                "danger"
            )

            return redirect(
                url_for(
                    "nuevo_usuario_unidad",
                    id=unidad.id
                )
            )

        if rol == "ADMIN" and not getattr(current_user, "administrador_principal", False):
            flash(
            "Solo el Administrador Principal puede crear gerentes de sucursal.",
                "danger"
            )
            return redirect(
                url_for("nuevo_usuario_unidad", id=unidad.id)
            )

        # -----------------------------------------------------
        # CREAR USUARIO
        # -----------------------------------------------------

        modulos_seleccionados = set(request.form.getlist("modulos"))
        modulos_habilitados = modulos_habilitados_empresa(unidad.empresa)
        modulos_disponibles = modulos_habilitados & set(MODULOS_PERMISOS_USUARIO)
        if not getattr(current_user, "administrador_principal", False):
            modulos_disponibles.intersection_update({
                permiso.modulo for permiso in current_user.permisos
                if permiso.puede_ver
            })
        if rol in roles_personalizados:
            modulos_seleccionados = roles_personalizados[rol]
        elif not modulos_seleccionados:
            modulos_seleccionados = {
                "DASHBOARD", "PRODUCTOS", "INVENTARIO", "COMPRAS",
                "VENTAS", "CLIENTES", "PROVEEDORES", "APARTADOS",
                "CAJA", "REPORTES"
            } if rol == "ADMIN" else (
                {"DASHBOARD", "PRODUCTOS", "INVENTARIO", "VENTAS", "CLIENTES", "REPORTES"}
                if rol == "SUPERVISOR" else {"DASHBOARD", "PRODUCTOS", "VENTAS"}
            )
        if not modulos_seleccionados.issubset(modulos_disponibles):
            flash("La selección contiene permisos no válidos.", "danger")
            return redirect(url_for("nuevo_usuario_unidad", id=unidad.id))
        modulos_seleccionados.add("DASHBOARD")

        nuevo_usuario = Usuario(

            empresa_id=unidad.empresa_id,

            unidad_negocio_id=unidad.id,

            nombre=nombre,

            usuario=usuario,

            password=generate_password_hash(
                password
            ),

            rol=rol,

            activo=True,

            primer_acceso=True,

            administrador_principal=False

        )

        db.session.add(
            nuevo_usuario
        )

        try:

            db.session.flush()
            db.session.add_all([
                PermisoUsuario(
                    usuario_id=nuevo_usuario.id,
                    modulo=modulo,
                    puede_ver=True
                )
                for modulo in sorted(modulos_seleccionados)
            ])

            db.session.commit()

            flash(
                f"Usuario '{usuario}' creado correctamente.",
                "success"
            )

            return redirect(
                url_for(
                    "usuarios_unidad",
                    id=unidad.id
                )
            )

        except Exception as e:

            db.session.rollback()

            flash(
                f"Error al crear el usuario: {e}",
                "danger"
            )

            return redirect(
                url_for(
                    "nuevo_usuario_unidad",
                    id=unidad.id
                )
            )

    return render_template(
        "nuevo_usuario_unidad.html",
        unidad=unidad,
        modulos=sorted(
            (
                modulos_habilitados_empresa(unidad.empresa)
                & set(MODULOS_PERMISOS_USUARIO)
            ) if getattr(current_user, "administrador_principal", False) else (
                modulos_habilitados_empresa(unidad.empresa)
                & set(MODULOS_PERMISOS_USUARIO)
                & {permiso.modulo for permiso in current_user.permisos if permiso.puede_ver}
            )
        ),
        roles_disponibles=(
            ["ADMIN", "SUPERVISOR", "EMPLEADO"]
            if getattr(current_user, "administrador_principal", False)
            else ["SUPERVISOR", "EMPLEADO"]
        ) + sorted(roles_personalizados_empresa(unidad.empresa_id)),
    )


###############################################################
# USUARIOS DE UNA UNIDAD DE NEGOCIO
###############################################################

@app.route(
    "/unidades/<int:id>/usuarios"
)
@login_required
def usuarios_unidad(id):
    # ---------------------------------------------------------
    # BUSCAR UNIDAD
    # ---------------------------------------------------------

    unidad = UnidadNegocio.query.get_or_404(id)

    if not puede_gestionar_unidad(unidad):
        abort(403)

    # ---------------------------------------------------------
    # BUSCAR EMPRESA
    # ---------------------------------------------------------

    empresa = Empresa.query.get_or_404(
        unidad.empresa_id
    )

    # ---------------------------------------------------------
    # USUARIOS DE LA UNIDAD
    # ---------------------------------------------------------

    usuarios_lista = Usuario.query.filter_by(
        unidad_negocio_id=unidad.id
    ).order_by(
        Usuario.nombre
    ).all()

    return render_template(
        "usuarios_unidad.html",

        empresa=empresa,

        unidad=unidad,

        usuarios=usuarios_lista
    )


###############################################################
# USUARIOS
###############################################################

@app.route("/usuarios")
@login_required
def usuarios():
    # ---------------------------------------------------------
    # ADMINISTRADOR PRINCIPAL
    # ---------------------------------------------------------

    if getattr(
        current_user,
        "administrador_principal",
        False
    ):

        lista = Usuario.query.order_by(
            Usuario.nombre
        ).all()

    elif current_user.unidad_negocio_id is None and current_user.empresa_id:
        if not tiene_permiso("SEGURIDAD") or not current_user.empresa_id:
            abort(403)
        lista = Usuario.query.filter_by(
            empresa_id=current_user.empresa_id
        ).order_by(Usuario.nombre).all()
    else:
        if not tiene_permiso("SEGURIDAD") or not current_user.unidad_negocio_id:
            abort(403)
        lista = Usuario.query.filter_by(
            unidad_negocio_id=current_user.unidad_negocio_id
        ).order_by(Usuario.nombre).all()

    return render_template(
        "usuarios.html",
        usuarios=lista
    )


###############################################################
# EDITAR USUARIO
###############################################################

@app.route(
    "/usuarios/<int:id>/editar",
    methods=["GET", "POST"]
)
@login_required
def editar_usuario(id):

    usuario = Usuario.query.get_or_404(id)

    if usuario.administrador_principal:
        abort(403)

    if not puede_administrar_usuario(usuario):
        abort(403)

    roles_personalizados = roles_personalizados_empresa(usuario.empresa_id) if usuario.empresa_id else {}
    roles_validos = (
        ["GERENTE_EMPRESA"]
        if usuario.unidad_negocio_id is None and usuario.empresa_id is not None
        else ["ADMIN", "SUPERVISOR", "EMPLEADO", *roles_personalizados.keys()]
    )
    if not getattr(current_user, "administrador_principal", False):
        roles_validos = [rol_valido for rol_valido in roles_validos if rol_valido != "ADMIN"]

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    if request.method == "POST":

        nombre = request.form.get(
            "nombre",
            ""
        ).strip()

        usuario_login = request.form.get(
            "usuario",
            ""
        ).strip()

        rol = request.form.get(
            "rol",
            "EMPLEADO"
        ).strip().upper()

        activo = request.form.get(
            "activo"
        ) == "1"

        password = request.form.get(
            "password",
            ""
        )

        # -----------------------------------------------------
        # VALIDAR NOMBRE
        # -----------------------------------------------------

        if not nombre:

            flash(
                "El nombre del usuario es obligatorio.",
                "warning"
            )

            return redirect(
                url_for(
                    "editar_usuario",
                    id=usuario.id
                )
            )

        # -----------------------------------------------------
        # VALIDAR USUARIO
        # -----------------------------------------------------

        if not usuario_login:

            flash(
                "El nombre de usuario es obligatorio.",
                "warning"
            )

            return redirect(
                url_for(
                    "editar_usuario",
                    id=usuario.id
                )
            )

        # -----------------------------------------------------
        # VALIDAR ROL
        # -----------------------------------------------------

        if rol not in roles_validos:

            flash(
                "El rol seleccionado no es válido.",
                "danger"
            )

            return redirect(
                url_for(
                    "editar_usuario",
                    id=usuario.id
                )
            )

        if (
            not getattr(current_user, "administrador_principal", False)
            and rol == "ADMIN"
        ):
            flash(
                "Un ADMIN no puede asignar el rol ADMIN.",
                "danger"
            )
            return redirect(
                url_for("editar_usuario", id=usuario.id)
            )

        # -----------------------------------------------------
        # USUARIO DUPLICADO
        # -----------------------------------------------------

        existente = Usuario.query.filter(
            Usuario.usuario == usuario_login,
            Usuario.id != usuario.id
        ).first()

        if existente:

            flash(
                "Ese nombre de usuario ya existe.",
                "warning"
            )

            return redirect(
                url_for(
                    "editar_usuario",
                    id=usuario.id
                )
            )

        # -----------------------------------------------------
        # ACTUALIZAR
        # -----------------------------------------------------

        usuario.nombre = nombre

        usuario.usuario = usuario_login

        usuario.rol = rol

        usuario.activo = activo

        # -----------------------------------------------------
        # CONTRASEÑA OPCIONAL
        # -----------------------------------------------------

        if password:

            if len(password) < 8:
                flash(
                    "La contraseña nueva debe tener al menos 8 caracteres.",
                    "warning"
                )
                return redirect(url_for("editar_usuario", id=usuario.id))

            usuario.password = generate_password_hash(
                password
            )

            usuario.primer_acceso = True

        # -----------------------------------------------------
        # GUARDAR
        # -----------------------------------------------------

        try:

            db.session.commit()

            flash(
                f"Usuario '{usuario.usuario}' actualizado correctamente.",
                "success"
            )

            # Regresar a usuarios de la unidad
            if usuario.unidad_negocio_id:

                return redirect(
                    url_for(
                        "usuarios_unidad",
                        id=usuario.unidad_negocio_id
                    )
                )

            return redirect(
                url_for(
                    "usuarios"
                )
            )

        except Exception as e:

            db.session.rollback()

            flash(
                f"Error al actualizar usuario: {e}",
                "danger"
            )

            return redirect(
                url_for(
                    "editar_usuario",
                    id=usuario.id
                )
            )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    return render_template(
        "editar_usuario.html",
        usuario=usuario,
        roles_disponibles=roles_validos
    )


@app.route("/usuarios/<int:id>/restablecer-password", methods=["POST"])
@login_required
def restablecer_password_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    if not puede_administrar_usuario(usuario) or usuario.administrador_principal:
        abort(403)

    password_temporal = secrets.token_urlsafe(10)
    usuario.password = generate_password_hash(password_temporal)
    usuario.primer_acceso = True
    try:
        db.session.commit()
        flash(
            f"Contraseña temporal de {usuario.usuario}: {password_temporal}. "
            "Entrégala al usuario por un canal privado; deberá cambiarla al ingresar.",
            "warning"
        )
    except Exception as e:
        db.session.rollback()
        flash(f"No se pudo restablecer la contraseña: {e}", "danger")

    if usuario.unidad_negocio_id:
        return redirect(url_for("usuarios_unidad", id=usuario.unidad_negocio_id))
    return redirect(url_for("usuarios"))


###############################################################
# CAMBIAR ESTADO DE USUARIO
###############################################################

@app.route(
    "/usuarios/<int:id>/estado",
    methods=["POST"]
)
@login_required
def cambiar_estado_usuario(id):

    usuario = Usuario.query.get_or_404(id)

    if not puede_administrar_usuario(usuario):
        abort(403)

    # Evitar desactivar al Administrador Principal

    if usuario.administrador_principal:

        flash(
            "El Administrador Principal no puede desactivarse.",
            "danger"
        )

        return redirect(
            url_for(
                "usuarios"
            )
        )

    usuario.activo = not usuario.activo

    db.session.commit()

    estado = (
        "activado"
        if usuario.activo
        else "desactivado"
    )

    flash(
        f"Usuario '{usuario.usuario}' {estado} correctamente.",
        "success"
    )

    if usuario.unidad_negocio_id:

        return redirect(
            url_for(
                "usuarios_unidad",
                id=usuario.unidad_negocio_id
            )
        )

    return redirect(
        url_for(
            "usuarios"
        )
    )


###############################################################
# ELIMINAR USUARIO
###############################################################

@app.route(
    "/usuarios/<int:id>/eliminar",
    methods=["POST"]
)
@login_required
def eliminar_usuario(id):

    usuario = Usuario.query.get_or_404(id)

    if not puede_administrar_usuario(usuario):
        abort(403)

    # Nunca eliminar Administrador Principal

    if usuario.administrador_principal:

        flash(
            "El Administrador Principal no puede eliminarse.",
            "danger"
        )

        return redirect(
            url_for(
                "usuarios"
            )
        )

    unidad_id = usuario.unidad_negocio_id

    nombre_usuario = usuario.usuario

    try:

        PermisoUsuario.query.filter_by(
            usuario_id=usuario.id
        ).delete(synchronize_session=False)

        db.session.delete(
            usuario
        )

        db.session.commit()

        flash(
            f"Usuario '{nombre_usuario}' eliminado correctamente.",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(
            f"No se pudo eliminar el usuario: {e}",
            "danger"
        )

    if unidad_id:

        return redirect(
            url_for(
                "usuarios_unidad",
                id=unidad_id
            )
        )

    return redirect(
        url_for(
            "usuarios"
        )
    )

###############################################################
# PERMISOS DE USUARIO
###############################################################

@app.route("/usuarios/<int:id>/permisos", methods=["GET", "POST"])
@login_required
def permisos_usuario(id):

    usuario = Usuario.query.get_or_404(id)

    if usuario.administrador_principal:
        abort(403)

    if not puede_administrar_usuario(usuario):
        abort(403)

    modulos = list(
        modulos_habilitados_empresa(usuario.empresa)
        & set(MODULOS_PERMISOS_USUARIO)
    )
    if not getattr(current_user, "administrador_principal", False):
        modulos = [
            modulo for modulo in modulos
            if tiene_permiso(modulo)
        ]
    if "DASHBOARD" not in modulos:
        modulos.append("DASHBOARD")

    if request.method == "POST":

        try:

            # Eliminar permisos actuales
            PermisoUsuario.query.filter_by(
                usuario_id=usuario.id
            ).delete()

            # Crear nuevamente los permisos seleccionados
            for modulo in modulos:

                if request.form.get(modulo) == "1":

                    permiso = PermisoUsuario(
                        usuario_id=usuario.id,
                        modulo=modulo,
                        puede_ver=True
                    )

                    db.session.add(permiso)

            db.session.commit()

            flash(
                "Permisos actualizados correctamente.",
                "success"
            )

        except Exception as e:

            db.session.rollback()

            flash(
                f"Error al actualizar permisos: {e}",
                "danger"
            )

        if usuario.unidad_negocio_id:
            return redirect(
                url_for("usuarios_unidad", id=usuario.unidad_negocio_id)
            )

        return redirect(url_for("usuarios"))

    permisos_actuales = PermisoUsuario.query.filter_by(
        usuario_id=usuario.id,
        puede_ver=True
    ).all()

    permisos_seleccionados = {
        permiso.modulo
        for permiso in permisos_actuales
    }

    return render_template(
        "permisos_usuario.html",
        usuario=usuario,
        modulos=modulos,
        permisos_seleccionados=permisos_seleccionados,
        retorno_unidad_id=usuario.unidad_negocio_id
    )
###############################################################
# PANEL CORPORATIVO
# ADMINISTRADOR PRINCIPAL / UNIVERSAL
###############################################################

@app.route("/panel-corporativo")
@login_required
def panel_corporativo():

    if not getattr(
        current_user,
        "administrador_principal",
        False
    ):
        abort(403)

    empresas = Empresa.query.order_by(
        Empresa.nombre
    ).all()

    return render_template(
        "panel_corporativo.html",
        empresas=empresas
    )


###############################################################
# PANEL CORPORATIVO - EMPRESA

###############################################################

@app.route(
    "/panel-corporativo/empresa/<int:id>"
)
@login_required
def panel_corporativo_empresa(id):

    principal = getattr(current_user, "administrador_principal", False)
    gerente_empresa = (
        current_user.unidad_negocio_id is None
        and current_user.empresa_id is not None
        and current_user.empresa_id == id
        and any(tiene_permiso(modulo) for modulo in ("REPORTES", "ANALISIS_DATOS", "SEGURIDAD", "CONFIGURACION"))
    )
    if not principal and not gerente_empresa:
        abort(403)

    empresa = Empresa.query.get_or_404(id)

    unidades = UnidadNegocio.query.filter_by(
        empresa_id=empresa.id
    ).order_by(
        UnidadNegocio.nombre
    ).all()

    unidad_ids = [unidad.id for unidad in unidades]
    puede_ver_reportes = principal or tiene_permiso("REPORTES")
    puede_ver_analisis = principal or tiene_permiso("ANALISIS_DATOS") or tiene_permiso("REPORTES")
    total_ventas = 0 if puede_ver_reportes else None
    total_compras = 0 if puede_ver_reportes else None
    if unidad_ids and puede_ver_reportes:
        total_ventas = db.session.query(
            func.coalesce(func.sum(Venta.total), 0)
        ).filter(
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA"
        ).scalar() or 0
        total_compras = db.session.query(
            func.coalesce(func.sum(Compra.total), 0)
        ).filter(
            Compra.unidad_negocio_id.in_(unidad_ids)
        ).scalar() or 0

    total_usuarios = Usuario.query.filter_by(empresa_id=empresa.id).count() if (principal or tiene_permiso("SEGURIDAD")) else None
    total_productos = Producto.query.filter(
        Producto.unidad_negocio_id.in_(unidad_ids)
    ).count() if unidad_ids and puede_ver_reportes else None

    return render_template(
        "panel_corporativo_empresa.html",
        empresa=empresa,
        unidades=unidades,
        total_ventas=total_ventas,
        total_compras=total_compras,
        total_usuarios=total_usuarios,
        total_productos=total_productos,
        utilidad_estimada=(total_ventas - total_compras) if puede_ver_reportes else None,
        puede_administrar=puede_administrar_empresa(empresa),
        puede_gestionar_usuarios=principal or tiene_permiso("SEGURIDAD"),
        puede_ver_reportes=puede_ver_reportes,
        puede_ver_analisis=puede_ver_analisis
    )


###############################################################
# PANEL CORPORATIVO - SELECCIONAR UNIDAD
###############################################################

@app.route(
    "/panel-corporativo/unidad/<int:id>"
)
@login_required
def seleccionar_unidad_corporativa(id):

    if not getattr(
        current_user,
        "administrador_principal",
        False
    ):
        abort(403)

    unidad = UnidadNegocio.query.get_or_404(id)

    empresa = Empresa.query.get_or_404(
        unidad.empresa_id
    )

    # Guardamos el contexto administrativo
    session["empresa_admin_id"] = empresa.id

    session["unidad_admin_id"] = unidad.id

    flash(
        f"Unidad '{unidad.nombre}' seleccionada.",
        "success"
    )

    return redirect(
        url_for(
            "panel_unidad_corporativa",
            id=unidad.id
        )
    )


###############################################################
# PANEL DE UNIDAD CORPORATIVA
###############################################################

@app.route(
    "/panel-corporativo/unidad/<int:id>/panel"
)
@login_required
def panel_unidad_corporativa(id):

    principal = getattr(current_user, "administrador_principal", False)
    gerente_empresa = (
        current_user.unidad_negocio_id is None
        and current_user.empresa_id is not None
        and any(tiene_permiso(modulo) for modulo in ("REPORTES", "ANALISIS_DATOS", "SEGURIDAD", "CONFIGURACION"))
    )
    if not principal and not gerente_empresa and str(getattr(current_user, "rol", "")).upper() != "ADMIN":
        abort(403)

    unidad = UnidadNegocio.query.get_or_404(id)
    if gerente_empresa and unidad.empresa_id != current_user.empresa_id:
        abort(403)
    if not principal and not gerente_empresa and unidad.id != current_user.unidad_negocio_id:
        abort(403)

    empresa = Empresa.query.get_or_404(
        unidad.empresa_id
    )

    usuarios = Usuario.query.filter_by(
        unidad_negocio_id=unidad.id
    ).order_by(
        Usuario.nombre
    ).all()

    productos = Producto.query.filter_by(
        unidad_negocio_id=unidad.id
    ).count()

    clientes = Cliente.query.filter_by(
        unidad_negocio_id=unidad.id
    ).count()

    ventas = Venta.query.filter_by(
        unidad_negocio_id=unidad.id
    ).count()

    compras = Compra.query.filter_by(
        unidad_negocio_id=unidad.id
    ).count()

    apartados = Apartado.query.filter_by(
        unidad_negocio_id=unidad.id
    ).count()

    cajas = Caja.query.filter_by(
        unidad_negocio_id=unidad.id
    ).count()

    hoy = date.today()
    puede_ver_reportes = principal or tiene_permiso("REPORTES")
    puede_ver_analisis = principal or tiene_permiso("ANALISIS_DATOS") or tiene_permiso("REPORTES")
    metricas_unidad = _metricas_analisis(
        [unidad.id],
        datetime(hoy.year, 1, 1),
        datetime.combine(hoy + timedelta(days=1), datetime.min.time())
    ) if puede_ver_reportes else None

    return render_template(
        "panel_unidad_corporativa.html",

        empresa=empresa,

        unidad=unidad,

        usuarios=usuarios,

        total_productos=productos,

        total_clientes=clientes,

        total_ventas=ventas,

        total_compras=compras,

        total_apartados=apartados,

        total_cajas=cajas,
        metricas=metricas_unidad,
        puede_gestionar_usuarios=puede_gestionar_unidad(unidad),
        puede_configurar_unidad=(
            puede_administrar_empresa(empresa)
            or (
                str(getattr(current_user, "rol", "")).upper() == "ADMIN"
                and unidad.id == current_user.unidad_negocio_id
                and tiene_permiso("CONFIGURACION")
            )
        ),
        puede_ver_reportes=puede_ver_reportes,
        puede_ver_analisis=puede_ver_analisis
    )

###############################################################
# APARTADOS
###############################################################

def _caja_abierta_unidad():
    return Caja.query.filter_by(
        unidad_negocio_id=current_user.unidad_negocio_id,
        abierta=True
    ).first()


def _apartado_operable(id):
    apartado = Apartado.query.get_or_404(id)
    validar_unidad_registro(apartado)
    if apartado.unidad_negocio_id != current_user.unidad_negocio_id:
        abort(403)
    return apartado


def _registrar_pago_apartado(apartado, caja, monto, metodo, observaciones):
    db.session.add(PagoApartado(
        apartado_id=apartado.id,
        monto=monto,
        metodo_pago=metodo,
        usuario_id=current_user.id,
        observaciones=observaciones
    ))
    db.session.add(MovimientoCaja(
        caja_id=caja.id,
        tipo="ENTRADA",
        monto=monto,
        usuario_id=current_user.id,
        observaciones=f"Abono apartado {apartado.numero_apartado} ({metodo})"
    ))
    if metodo == "EFECTIVO":
        caja.saldo_actual = (caja.saldo_actual or 0) + monto


@app.route("/apartados")
@login_required
@modulo_requerido("APARTADOS")
def apartados():

    lista = (
        filtro_unidad(Apartado.query, Apartado)
        .order_by(Apartado.fecha.desc())
        .all()
    )

    return render_template(
        "apartados.html",
        apartados=lista,
        today=date.today()
    )


@app.route("/apartados/nuevo", methods=["GET", "POST"])
@login_required
@modulo_requerido("APARTADOS")
def nuevo_apartado():

    unidad_id = current_user.unidad_negocio_id
    if not unidad_id:
        flash("Selecciona una sucursal para registrar apartados.", "warning")
        return redirect(url_for("apartados"))

    productos_db = Producto.query.filter(
        Producto.unidad_negocio_id == unidad_id,
        Producto.activo == True
    ).order_by(Producto.nombre).all()

    clientes_db = Cliente.query.filter(
        Cliente.unidad_negocio_id == unidad_id,
        Cliente.activo == True
    ).order_by(Cliente.nombre).all()

    config = Configuracion.query.filter_by(unidad_negocio_id=unidad_id).first()
    if not config:
        config = Configuracion(unidad_negocio_id=unidad_id)
        db.session.add(config)
        db.session.commit()

    if request.method == "GET":

        hoy = date.today()
        return render_template(
            "nuevo_apartado.html",
            productos=[
                {
                    "id": p.id,
                    "codigo": p.codigo,
                    "nombre": p.nombre,
                    "talla": p.talla,
                    "color": p.color,
                    "precio": float(p.precio or 0),
                    "imagen": p.imagen,
                    "stock": stock_producto(p.id, unidad_id),
                }
                for p in productos_db
            ],
            clientes=[
                {
                    "id": c.id,
                    "nombre": c.nombre,
                    "telefono": c.telefono,
                    "puntos": c.puntos or 0
                }
                for c in clientes_db
            ],
            config={
                campo: getattr(config, campo)
                for campo in (
                    "mayoreo_activo", "descuento_3_5", "descuento_6_10",
                    "descuento_11_mas", "descuento_adicional_activo",
                    "descuento_adicional_porcentaje", "fidelidad_activa",
                    "porcentaje_fidelidad", "anticipo_minimo_porcentaje",
                )
            },
            hoy=hoy.isoformat(),
            fecha_default=(hoy + timedelta(days=30)).isoformat()
        )

    caja = _caja_abierta_unidad()
    if not caja:
        flash(
            "La caja está cerrada. El gerente debe abrir la jornada para registrar apartados.",
            "warning"
        )
        return redirect(url_for("apartados"))

    try:

        if not config.apartados_activos:
            raise ValueError("Los apartados están desactivados en esta sucursal.")

        try:
            carrito = json.loads(request.form.get("carrito") or "[]")
        except ValueError:
            carrito = []
        if not carrito:
            raise ValueError("Agrega al menos un producto.")

        permitidos = {p.id: p for p in productos_db}
        cantidades = {}
        for item in carrito:
            pid = int(item.get("producto_id"))
            cant = int(item.get("cantidad"))
            if pid not in permitidos or cant <= 0:
                raise ValueError("Producto inválido en el apartado.")
            cantidades[pid] = cantidades.get(pid, 0) + cant

        cliente = next(
            (c for c in clientes_db
             if c.id == request.form.get("cliente_id", type=int)),
            None
        )
        if not cliente:
            raise ValueError("Selecciona un cliente válido.")

        try:
            limite = datetime.strptime(
                request.form.get("fecha_vencimiento", ""), "%Y-%m-%d"
            ).date()
        except ValueError:
            raise ValueError("Fecha de vencimiento inválida.")
        if limite < date.today():
            raise ValueError("La fecha de vencimiento no puede ser pasada.")

        subtotal = sum(
            permitidos[pid].precio * cant for pid, cant in cantidades.items()
        )
        piezas = sum(cantidades.values())

        descuento_mayoreo = 0
        if request.form.get("mayoreo") and config.mayoreo_activo:
            if piezas >= 11:
                descuento_mayoreo = subtotal * config.descuento_11_mas / 100
            elif piezas >= 6:
                descuento_mayoreo = subtotal * config.descuento_6_10 / 100
            elif piezas >= 3:
                descuento_mayoreo = subtotal * config.descuento_3_5 / 100
        base = subtotal - descuento_mayoreo
        descuento_adicional = 0
        if request.form.get("desc_adicional") and config.descuento_adicional_activo:
            descuento_adicional = base * config.descuento_adicional_porcentaje / 100
        base -= descuento_adicional
        descuento_fidelidad = 0
        if request.form.get("desc_fidelidad") and config.fidelidad_activa:
            descuento_fidelidad = base * config.porcentaje_fidelidad / 100
        total = round(
            subtotal - descuento_mayoreo - descuento_adicional - descuento_fidelidad, 2
        )

        anticipo = round(request.form.get("anticipo", type=float) or 0, 2)
        minimo = round(total * (config.anticipo_minimo_porcentaje or 0) / 100, 2)
        if anticipo + 0.005 < minimo:
            raise ValueError(f"El anticipo mínimo es ${minimo:,.2f}.")
        if anticipo > total + 0.005:
            raise ValueError("El anticipo no puede superar el total.")
        metodo = request.form.get("metodo_pago", "EFECTIVO")
        if metodo not in ("EFECTIVO", "TARJETA", "TRANSFERENCIA"):
            metodo = "EFECTIVO"

        apartado = Apartado(
            numero_apartado=generar_numero_apartado(),
            cliente_id=cliente.id,
            unidad_negocio_id=unidad_id,
            fecha_limite=limite,
            total=total,
            enganche=anticipo,
            saldo=total,
            estado="ACTIVO",
            observaciones=(request.form.get("observaciones") or "")[:300]
        )
        db.session.add(apartado)
        db.session.flush()

        for pid, cant in cantidades.items():
            producto = permitidos[pid]
            if not mover_inventario(
                producto_id=pid,
                unidad_id=unidad_id,
                cantidad=cant,
                tipo="APARTADO",
                usuario_id=current_user.id,
                referencia=apartado.numero_apartado,
                observaciones="Apartado"
            ):
                raise ValueError(
                    f"No hay existencias suficientes de {producto.nombre}."
                )
            producto.stock = stock_producto(pid, unidad_id)
            db.session.add(DetalleApartado(
                apartado_id=apartado.id,
                producto_id=pid,
                cantidad=cant,
                precio_unitario=producto.precio,
                subtotal=producto.precio * cant
            ))

        if anticipo > 0:
            _registrar_pago_apartado(
                apartado, caja, anticipo, metodo, "Anticipo inicial"
            )
        db.session.flush()
        db.session.refresh(apartado)
        calcular_saldo_apartado(apartado)

        registrar_auditoria("APARTADOS", "CREAR", apartado.numero_apartado)
        db.session.commit()

        flash(f"Apartado {apartado.numero_apartado} registrado.", "success")
        return redirect(url_for("detalle_apartado", id=apartado.id))

    except Exception as e:

        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("nuevo_apartado"))


@app.route("/apartados/<int:id>")
@login_required
@modulo_requerido("APARTADOS")
def detalle_apartado(id):

    apartado = Apartado.query.get_or_404(id)
    validar_unidad_registro(apartado)

    cambios = []
    for c in CambioApartado.query.filter_by(
        apartado_id=apartado.id
    ).order_by(CambioApartado.fecha).all():
        anterior = Producto.query.get(c.producto_anterior_id)
        nuevo = Producto.query.get(c.producto_nuevo_id)
        diferencia = ((c.precio_nuevo or 0) - (c.precio_anterior or 0)) * (c.cantidad or 0)
        cambios.append({
            "fecha": c.fecha,
            "producto_anterior": anterior.nombre if anterior else "-",
            "producto_nuevo": nuevo.nombre if nuevo else "-",
            "cantidad": c.cantidad,
            "precio_anterior": c.precio_anterior or 0,
            "precio_nuevo": c.precio_nuevo or 0,
            "diferencia": diferencia,
            "saldo_nuevo": apartado.saldo,
            "usuario": c.usuario_id and Usuario.query.get(c.usuario_id),
        })
    for c in cambios:
        if c["usuario"] is None:
            c["usuario"] = {"nombre": "-"}

    return render_template(
        "detalle_apartado.html",
        apartado=apartado,
        cambios=cambios,
        today=date.today()
    )


@app.route("/apartados/<int:id>/abonar", methods=["POST"])
@login_required
@modulo_requerido("APARTADOS")
def abonar_apartado(id):

    apartado = _apartado_operable(id)

    try:
        if apartado.estado != "ACTIVO" or apartado.entregado:
            raise ValueError("Este apartado ya no admite abonos.")
        caja = _caja_abierta_unidad()
        if not caja:
            raise ValueError("La caja está cerrada. El gerente debe abrir la jornada.")
        monto = round(request.form.get("monto", type=float) or 0, 2)
        if monto <= 0:
            raise ValueError("Monto inválido.")
        if monto > apartado.saldo + 0.005:
            raise ValueError("El abono no puede superar el saldo.")
        metodo = request.form.get("metodo_pago", "EFECTIVO")
        if metodo not in ("EFECTIVO", "TARJETA", "TRANSFERENCIA"):
            metodo = "EFECTIVO"

        _registrar_pago_apartado(
            apartado, caja, monto, metodo,
            (request.form.get("observaciones") or "")[:300]
        )
        db.session.flush()
        db.session.refresh(apartado)
        calcular_saldo_apartado(apartado)
        registrar_auditoria(
            "APARTADOS", "ABONO", f"{apartado.numero_apartado} ${monto:,.2f}"
        )
        db.session.commit()
        flash("Abono registrado.", "success")
    except Exception as e:
        db.session.rollback()
        flash(str(e), "danger")

    return redirect(url_for("detalle_apartado", id=id))


@app.route("/apartados/<int:id>/entregar", methods=["POST"])
@login_required
@modulo_requerido("APARTADOS")
def entregar_apartado(id):

    apartado = _apartado_operable(id)

    if apartado.estado != "LIQUIDADO" or apartado.entregado:
        flash("Solo se entregan apartados liquidados.", "danger")
        return redirect(url_for("detalle_apartado", id=id))

    apartado.entregado = True
    apartado.estado = "ENTREGADO"
    apartado.fecha_entrega = datetime.now()

    config = Configuracion.query.filter_by(
        unidad_negocio_id=apartado.unidad_negocio_id
    ).first()
    cliente = apartado.cliente
    if cliente and config and config.fidelidad_activa and config.puntos_por_peso:
        puntos = int(apartado.total / config.puntos_por_peso)
        if puntos > 0:
            cliente.puntos = (cliente.puntos or 0) + puntos
            apartado.puntos_otorgados = puntos
            db.session.add(MovimientoPuntos(
                cliente_id=cliente.id,
                puntos=puntos,
                tipo="APARTADO",
                usuario_id=current_user.id,
                observaciones=apartado.numero_apartado
            ))

    registrar_auditoria("APARTADOS", "ENTREGAR", apartado.numero_apartado)
    db.session.commit()
    flash("Apartado entregado.", "success")
    return redirect(url_for("detalle_apartado", id=id))


@app.route("/apartados/<int:id>/cancelar", methods=["POST"])
@login_required
@modulo_requerido("APARTADOS")
def cancelar_apartado(id):

    apartado = _apartado_operable(id)

    if not es_gerente_caja():
        abort(403)

    if apartado.estado != "ACTIVO" or apartado.entregado:
        flash("Este apartado no se puede cancelar.", "danger")
        return redirect(url_for("detalle_apartado", id=id))

    try:
        for d in apartado.detalles:
            mover_inventario(
                producto_id=d.producto_id,
                unidad_id=apartado.unidad_negocio_id,
                cantidad=d.cantidad,
                tipo="DEVOLUCION_ENTRADA",
                usuario_id=current_user.id,
                referencia=apartado.numero_apartado,
                observaciones="Cancelación de apartado"
            )
            d.producto.stock = stock_producto(
                d.producto_id, apartado.unidad_negocio_id
            )
        apartado.cancelado = True
        apartado.estado = "CANCELADO"
        registrar_auditoria("APARTADOS", "CANCELAR", apartado.numero_apartado)
        db.session.commit()
        flash("Apartado cancelado e inventario devuelto.", "success")
    except Exception as e:
        db.session.rollback()
        flash(str(e), "danger")

    return redirect(url_for("detalle_apartado", id=id))


@app.route("/apartados/<int:id>/cambiar", methods=["GET", "POST"])
@login_required
@modulo_requerido("APARTADOS")
def cambiar_apartado(id):

    apartado = _apartado_operable(id)

    if apartado.estado not in ("ACTIVO", "LIQUIDADO") or apartado.entregado:
        flash("Este apartado no admite cambios.", "danger")
        return redirect(url_for("detalle_apartado", id=id))

    productos = Producto.query.filter(
        Producto.unidad_negocio_id == apartado.unidad_negocio_id,
        Producto.activo == True
    ).order_by(Producto.nombre).all()
    for p in productos:
        p.stock = stock_producto(p.id, p.unidad_negocio_id)

    if request.method == "GET":
        return render_template(
            "cambiar_apartado.html", apartado=apartado, productos=productos
        )

    try:
        detalle = next(
            (d for d in apartado.detalles
             if d.id == request.form.get("detalle_id", type=int)),
            None
        )
        nuevo = next(
            (p for p in productos
             if p.id == request.form.get("producto_id", type=int)),
            None
        )
        cantidad = request.form.get("cantidad", type=int) or 0
        if not detalle or not nuevo or cantidad <= 0 or cantidad > detalle.cantidad:
            raise ValueError("Datos de cambio inválidos.")
        if nuevo.id == detalle.producto_id:
            raise ValueError("Selecciona un producto distinto.")

        unidad_id = apartado.unidad_negocio_id
        anterior = detalle.producto
        precio_anterior = detalle.precio_unitario

        if not mover_inventario(
            producto_id=nuevo.id, unidad_id=unidad_id, cantidad=cantidad,
            tipo="APARTADO", usuario_id=current_user.id,
            referencia=apartado.numero_apartado, observaciones="Cambio de apartado"
        ):
            raise ValueError(f"No hay existencias suficientes de {nuevo.nombre}.")
        mover_inventario(
            producto_id=anterior.id, unidad_id=unidad_id, cantidad=cantidad,
            tipo="DEVOLUCION_ENTRADA", usuario_id=current_user.id,
            referencia=apartado.numero_apartado, observaciones="Cambio de apartado"
        )
        anterior.stock = stock_producto(anterior.id, unidad_id)
        nuevo.stock = stock_producto(nuevo.id, unidad_id)

        detalle.cantidad -= cantidad
        detalle.subtotal = detalle.cantidad * detalle.precio_unitario
        if detalle.cantidad == 0:
            db.session.delete(detalle)
        db.session.add(DetalleApartado(
            apartado_id=apartado.id,
            producto_id=nuevo.id,
            cantidad=cantidad,
            precio_unitario=nuevo.precio,
            subtotal=nuevo.precio * cantidad
        ))
        apartado.total = round(
            (apartado.total or 0) + (nuevo.precio - precio_anterior) * cantidad, 2
        )
        db.session.add(CambioApartado(
            apartado_id=apartado.id,
            producto_anterior_id=anterior.id,
            producto_nuevo_id=nuevo.id,
            cantidad=cantidad,
            precio_anterior=precio_anterior,
            precio_nuevo=nuevo.precio,
            usuario_id=current_user.id
        ))
        db.session.flush()
        db.session.refresh(apartado)
        calcular_saldo_apartado(apartado)
        registrar_auditoria(
            "APARTADOS", "CAMBIO",
            f"{apartado.numero_apartado}: {anterior.nombre} -> {nuevo.nombre}"
        )
        db.session.commit()
        flash("Cambio registrado.", "success")
        return redirect(url_for("detalle_apartado", id=id))

    except Exception as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("cambiar_apartado", id=id))


###############################################################
# DETALLE POR SUCURSAL (SOLO CONSULTA)
###############################################################

def _autorizar_consulta_unidad(unidad):
    if getattr(current_user, "administrador_principal", False):
        return
    if (
        current_user.empresa_id == unidad.empresa_id
        and current_user.unidad_negocio_id is None
        and tiene_permiso("REPORTES")
    ):
        return
    if (
        str(getattr(current_user, "rol", "")).upper() == "ADMIN"
        and current_user.unidad_negocio_id == unidad.id
    ):
        return
    abort(403)


def _fmt_fecha(valor):
    return valor.strftime("%d/%m/%Y %H:%M") if valor else "-"


def _fmt_dinero(valor):
    return f"${(valor or 0):,.2f}"


SECCIONES_UNIDAD = {
    "ventas": "Ventas",
    "compras": "Compras",
    "productos": "Productos e inventario",
    "clientes": "Clientes",
    "proveedores": "Proveedores",
    "apartados": "Apartados",
    "usuarios": "Usuarios",
}


@app.route("/panel-corporativo/unidad/<int:id>/<seccion>")
@login_required
def unidad_seccion(id, seccion):

    unidad = UnidadNegocio.query.get_or_404(id)
    _autorizar_consulta_unidad(unidad)

    if seccion == "cajas":
        return redirect(url_for("caja_historial", unidad_id=unidad.id))
    if seccion not in SECCIONES_UNIDAD:
        abort(404)

    filtro = {"unidad_negocio_id": unidad.id}

    if seccion == "ventas":
        columnas = ["Folio", "Fecha", "Cliente", "Pago", "Total", "Estado"]
        filas = [
            [v.numero_venta, _fmt_fecha(v.fecha), v.cliente.nombre if v.cliente else "Mostrador",
             v.metodo_pago, _fmt_dinero(v.total), v.estado]
            for v in Venta.query.filter_by(**filtro).order_by(Venta.id.desc()).limit(200)
        ]
    elif seccion == "compras":
        columnas = ["Folio", "Fecha", "Proveedor", "Total"]
        filas = [
            [c.numero_compra, _fmt_fecha(c.fecha), c.proveedor.nombre if c.proveedor else "-",
             _fmt_dinero(c.total)]
            for c in Compra.query.filter_by(**filtro).order_by(Compra.id.desc()).limit(200)
        ]
    elif seccion == "productos":
        columnas = ["Código", "Producto", "Categoría", "Precio", "Existencia", "Mínimo"]
        filas = [
            [p.codigo, p.nombre, p.categoria or "-", _fmt_dinero(p.precio),
             stock_producto(p.id, unidad.id), p.stock_minimo]
            for p in Producto.query.filter_by(**filtro).order_by(Producto.nombre).limit(300)
        ]
    elif seccion == "clientes":
        columnas = ["Cliente", "Teléfono", "Correo", "Puntos"]
        filas = [
            [c.nombre, c.telefono or "-", c.correo or "-", c.puntos or 0]
            for c in Cliente.query.filter_by(**filtro).order_by(Cliente.nombre).limit(300)
        ]
    elif seccion == "proveedores":
        columnas = ["Proveedor", "Teléfono", "Correo"]
        filas = [
            [p.nombre, p.telefono or "-", p.correo or "-"]
            for p in Proveedor.query.filter_by(**filtro).order_by(Proveedor.nombre).limit(300)
        ]
    elif seccion == "apartados":
        columnas = ["Folio", "Fecha", "Cliente", "Total", "Saldo", "Estado"]
        filas = [
            [a.numero_apartado, _fmt_fecha(a.fecha), a.cliente.nombre if a.cliente else "-",
             _fmt_dinero(a.total), _fmt_dinero(a.saldo), a.estado]
            for a in Apartado.query.filter_by(**filtro).order_by(Apartado.id.desc()).limit(200)
        ]
    else:
        columnas = ["Nombre", "Usuario", "Rol", "Estado"]
        filas = [
            [u.nombre, u.usuario, u.rol, "Activo" if u.activo else "Inactivo"]
            for u in Usuario.query.filter_by(unidad_negocio_id=unidad.id).order_by(Usuario.nombre)
        ]

    return render_template(
        "unidad_seccion.html",
        unidad=unidad,
        empresa=unidad.empresa,
        secciones=SECCIONES_UNIDAD,
        seccion=seccion,
        columnas=columnas,
        filas=filas
    )


###############################################################
# PRODUCTOS
###############################################################

@app.route("/productos")
@login_required
@modulo_requerido("PRODUCTOS")
def productos():

    lista = filtro_unidad(
        Producto.query,
        Producto
    ).order_by(
        Producto.nombre
    ).all()

    return render_template(
        "productos.html",
        productos=lista
    )


###############################################################
# NUEVO PRODUCTO
###############################################################

@app.route("/productos/nuevo", methods=["GET", "POST"])
@login_required
@modulo_requerido("PRODUCTOS")
def nuevo_producto():

    unidades = UnidadNegocio.query.order_by(
        UnidadNegocio.nombre
    ).all() if current_user.administrador_principal else (
        UnidadNegocio.query.filter_by(
            id=current_user.unidad_negocio_id
        ).all() if current_user.unidad_negocio_id else []
    )

    if request.method == "POST":

        try:

            codigo = request.form["codigo"].strip()

            if Producto.query.filter_by(
                codigo=codigo
            ).first():

                raise ValueError(
                    "Ya existe un producto con ese código."
                )

            unidad_producto = unidad_asignable(
                int(request.form["unidad_negocio_id"])
            )

            producto = Producto(

                codigo=codigo,

                nombre=request.form["nombre"].strip(),

                unidad_negocio_id=unidad_producto.id,

                categoria=request.form.get("categoria"),

                talla=request.form.get("talla"),

                color=request.form.get("color"),

                precio=float(
                    request.form["precio"]
                ),

                costo_promedio=float(
                    request.form.get(
                        "costo_promedio",
                        0
                    )
                ),

                stock=0,

                stock_minimo=int(
                    request.form.get(
                        "stock_minimo",
                        5
                    )
                ),

                stock_maximo=int(
                    request.form.get(
                        "stock_maximo",
                        100
                    )
                ),

                punto_reorden=int(
                    request.form.get(
                        "punto_reorden",
                        10
                    )
                ),

                ubicacion=request.form.get(
                    "ubicacion"
                ),

                codigo_barras=request.form.get(
                    "codigo_barras"
                ),

                activo=True

            )

            archivo = request.files.get("imagen")

            if archivo and archivo.filename:

                nombre = secure_filename(
                    archivo.filename
                )

                archivo.save(
                    os.path.join(
                        app.config["UPLOAD_FOLDER"],
                        nombre
                    )
                )

                producto.imagen = nombre

            db.session.add(producto)

            db.session.flush()

            inventario = Inventario(

                producto_id=producto.id,

                unidad_negocio_id=producto.unidad_negocio_id,

                existencia=0,

                stock_minimo=producto.stock_minimo,

                stock_maximo=producto.stock_maximo,

                punto_reorden=producto.punto_reorden,

                ubicacion=producto.ubicacion

            )

            db.session.add(inventario)

            registrar_auditoria(

                "PRODUCTOS",

                "ALTA",

                producto.nombre

            )

            db.session.commit()

            flash(
                "Producto creado correctamente.",
                "success"
            )

            return redirect(
                url_for("productos")
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    return render_template(

        "nuevo_producto.html",

        unidades=unidades

    )

###############################################################
# EDITAR PRODUCTO
###############################################################

@app.route("/productos/editar/<int:id>", methods=["GET", "POST"])
@login_required
@modulo_requerido("PRODUCTOS")
def editar_producto(id):

    producto = Producto.query.get_or_404(id)

    validar_unidad_registro(producto)

    unidades = UnidadNegocio.query.order_by(
        UnidadNegocio.nombre
    ).all()

    if request.method == "POST":

        try:

            codigo = request.form["codigo"].strip()

            existe = Producto.query.filter(
                Producto.codigo == codigo,
                Producto.id != producto.id
            ).first()

            if existe:
                raise ValueError(
                    "Ya existe otro producto con ese código."
                )

            producto.codigo = codigo
            producto.nombre = request.form["nombre"].strip()
            producto.categoria = request.form.get("categoria")
            producto.talla = request.form.get("talla")
            producto.color = request.form.get("color")
            producto.precio = float(request.form["precio"])
            producto.costo_promedio = float(
                request.form.get(
                    "costo_promedio",
                    0
                )
            )

            producto.stock_minimo = int(
                request.form.get(
                    "stock_minimo",
                    5
                )
            )

            producto.stock_maximo = int(
                request.form.get(
                    "stock_maximo",
                    100
                )
            )

            producto.punto_reorden = int(
                request.form.get(
                    "punto_reorden",
                    10
                )
            )

            producto.ubicacion = request.form.get(
                "ubicacion"
            )

            producto.codigo_barras = request.form.get(
                "codigo_barras"
            )

            producto.activo = (
                "activo" in request.form
            )

            archivo = request.files.get("imagen")

            if archivo and archivo.filename:

                nombre = secure_filename(
                    archivo.filename
                )

                archivo.save(
                    os.path.join(
                        app.config["UPLOAD_FOLDER"],
                        nombre
                    )
                )

                producto.imagen = nombre

            inventario = Inventario.query.filter_by(
                producto_id=producto.id,
                unidad_negocio_id=producto.unidad_negocio_id
            ).first()

            if inventario:

                inventario.stock_minimo = producto.stock_minimo
                inventario.stock_maximo = producto.stock_maximo
                inventario.punto_reorden = producto.punto_reorden
                inventario.ubicacion = producto.ubicacion

            registrar_auditoria(

                "PRODUCTOS",

                "EDICIÓN",

                producto.nombre

            )

            db.session.commit()

            flash(
                "Producto actualizado correctamente.",
                "success"
            )

            return redirect(
                url_for("productos")
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    return render_template(

        "editar_producto.html",

        producto=producto,

        unidades=unidades

    )


###############################################################
# ELIMINAR PRODUCTO
###############################################################

@app.route("/productos/eliminar/<int:id>", methods=["POST"])
@login_required
@modulo_requerido("PRODUCTOS")
def eliminar_producto(id):

    producto = Producto.query.get_or_404(id)

    validar_unidad_registro(producto)

    try:

        movimientos = MovimientoInventario.query.filter_by(
            producto_id=producto.id
        ).count()

        if movimientos > 0:

            raise ValueError(
                "No puede eliminar un producto con movimientos."
            )

        Inventario.query.filter_by(
            producto_id=producto.id
        ).delete()

        registrar_auditoria(

            "PRODUCTOS",

            "ELIMINAR",

            producto.nombre

        )

        db.session.delete(producto)

        db.session.commit()

        flash(
            "Producto eliminado.",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(
            str(e),
            "danger"
        )

    return redirect(
        url_for("productos")
    )


###############################################################
# HISTORIAL DEL PRODUCTO
###############################################################

@app.route("/productos/<int:id>/movimientos")
@login_required
@modulo_requerido("PRODUCTOS")
def movimientos_producto(id):

    producto = Producto.query.get_or_404(id)

    validar_unidad_registro(producto)

    movimientos = MovimientoInventario.query.filter_by(
        producto_id=id
    ).order_by(
        MovimientoInventario.fecha.desc()
    ).all()

    return render_template(

        "movimientos_producto.html",

        producto=producto,

        movimientos=movimientos

    )

###############################################################
# VENTAS
###############################################################


# DUPLICADO ventas ELIMINADO


# DUPLICADO detalle_venta ELIMINADO

@app.route("/ventas/eliminar/<int:id>", methods=["POST"])
@login_required
@modulo_requerido("VENTAS")
def eliminar_venta(id):

    if current_user.rol != "ADMIN":

        flash(
            "Solo administradores.",
            "danger"
        )

        return redirect(url_for("ventas"))

    venta = Venta.query.get_or_404(id)

    validar_unidad_registro(venta)

    try:

        if venta.estado != "CANCELADA":

            raise ValueError(
                "Solo pueden eliminarse ventas canceladas."
            )

        for detalle in venta.detalles:

            db.session.delete(detalle)

        registrar_auditoria(

            "VENTAS",

            "ELIMINAR",

            venta.numero_venta

        )

        db.session.delete(venta)

        db.session.commit()

        flash(
            "Venta eliminada.",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(
            str(e),
            "danger"
        )

    return redirect(url_for("ventas"))

###############################################################
# NUEVA VENTA
###############################################################


# DUPLICADO nueva_venta ELIMINADO

@app.route("/ventas/editar/<int:id>", methods=["GET", "POST"])
@login_required
@modulo_requerido("VENTAS")
def editar_venta(id):

    venta = Venta.query.get_or_404(id)

    validar_unidad_registro(venta)

    if venta.estado != "ACTIVA":

        flash(
            "Solo pueden editarse ventas activas.",
            "danger"
        )

        return redirect(
            url_for("detalle_venta", id=id)
        )

    if venta_en_caja_cerrada(venta):

        flash(
            "La jornada de esta venta ya tiene corte de caja; solo es posible consultarla.",
            "danger"
        )

        return redirect(
            url_for("detalle_venta", id=id)
        )

    productos = filtro_unidad(
        Producto.query,
        Producto
    ).filter(
        Producto.activo == True
    ).order_by(
        Producto.nombre
    ).all()

    if request.method == "POST":

        try:

            detalle_id = int(
                request.form["detalle_id"]
            )

            nuevo_producto_id = int(
                request.form["producto_id"]
            )

            cantidad = int(
                request.form["cantidad"]
            )

            detalle = DetalleVenta.query.get_or_404(
                detalle_id
            )

            viejo = Producto.query.get(
                detalle.producto_id
            )

            nuevo = Producto.query.get(
                nuevo_producto_id
            )

            if cantidad > detalle.cantidad:

                raise ValueError(
                    "Cantidad inválida."
                )

            ###################################################
            # REGRESAR INVENTARIO DEL PRODUCTO ANTERIOR
            ###################################################

            if not mover_inventario(

                producto_id=viejo.id,

                unidad_id=venta.unidad_negocio_id,

                cantidad=cantidad,

                tipo="DEVOLUCION_ENTRADA",

                usuario_id=current_user.id,

                referencia=venta.numero_venta,

                observaciones="Cambio de venta"

            ):

                raise ValueError(
                    f"No fue posible regresar {viejo.nombre}"
                )

            ###################################################
            # DESCONTAR INVENTARIO DEL NUEVO PRODUCTO
            ###################################################

            if not mover_inventario(

                producto_id=nuevo.id,

                unidad_id=venta.unidad_negocio_id,

                cantidad=cantidad,

                tipo="VENTA",

                usuario_id=current_user.id,

                referencia=venta.numero_venta,

                observaciones="Cambio de venta"

            ):

                raise ValueError(
                    f"No existe inventario suficiente de {nuevo.nombre}"
                )

            ###################################################
            # SINCRONIZAR STOCK
            ###################################################

            viejo.stock = stock_producto(
                viejo.id,
                venta.unidad_negocio_id
            )

            nuevo.stock = stock_producto(
                nuevo.id,
                venta.unidad_negocio_id
            )

            ###################################################
            # ACTUALIZAR DETALLE
            ###################################################

            if cantidad == detalle.cantidad:

                detalle.producto_id = nuevo.id
                detalle.precio_unitario = nuevo.precio
                detalle.subtotal = nuevo.precio * cantidad

            else:

                detalle.cantidad -= cantidad
                detalle.subtotal = (
                    detalle.cantidad *
                    detalle.precio_unitario
                )

                nuevo_detalle = DetalleVenta(

                    venta_id=venta.id,

                    producto_id=nuevo.id,

                    cantidad=cantidad,

                    precio_unitario=nuevo.precio,

                    subtotal=nuevo.precio * cantidad

                )

                db.session.add(nuevo_detalle)

            ###################################################
            # RECALCULAR TOTAL
            ###################################################

            venta.subtotal = sum(
                d.subtotal
                for d in venta.detalles
            )

            total_anterior = venta.total

            venta.total = (
                venta.subtotal -
                venta.descuento
            )

            ###################################################
            # ACTUALIZAR MOVIMIENTO DE CAJA
            ###################################################

            movimiento = MovimientoCaja.query.filter_by(
                tipo="VENTA",
                origen_id=venta.id
            ).first()

            if movimiento:

                movimiento.monto = venta.total

                if movimiento.caja and venta.metodo_pago == "EFECTIVO":
                    movimiento.caja.saldo_actual = (
                        (movimiento.caja.saldo_actual or 0)
                        + venta.total - total_anterior
                    )

            ###################################################
            # RECALCULAR PUNTOS
            ###################################################

            if venta.cliente_id:

                cliente = Cliente.query.get(
                    venta.cliente_id
                )

                config = Configuracion.query.filter_by(
                    unidad_negocio_id=venta.unidad_negocio_id
                ).first()

                if cliente and config:

                    cliente.puntos = max(
                        0,
                        cliente.puntos -
                        venta.puntos_otorgados
                    )

                    nuevos_puntos = int(
                        venta.total /
                        config.puntos_por_peso
                    )

                    cliente.puntos += nuevos_puntos

                    venta.puntos_otorgados = nuevos_puntos

            ###################################################
            # MARCAR COMO EDITADA
            ###################################################

            venta.editada = True

            ###################################################
            # AUDITORÍA
            ###################################################

            registrar_auditoria(

                "VENTAS",

                "EDICION",

                venta.numero_venta

            )

            db.session.commit()

            flash(
                "Venta actualizada correctamente.",
                "success"
            )

            return redirect(
                url_for(
                    "detalle_venta",
                    id=venta.id
                )
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    return render_template(

        "editar_venta.html",

        venta=venta,

        productos=productos

    )

###############################################################
# CANCELAR VENTA
###############################################################

@app.route("/ventas/cancelar/<int:id>", methods=["POST"])
@login_required
@modulo_requerido("VENTAS")
def cancelar_venta(id):

    if current_user.rol != "ADMIN":
        flash("Solo los administradores pueden cancelar ventas.", "danger")
        return redirect(url_for("ventas"))

    venta = Venta.query.get_or_404(id)

    validar_unidad_registro(venta)

    try:

        if venta.estado == "CANCELADA":
            raise ValueError("Esta venta ya fue cancelada.")

        if venta_en_caja_cerrada(venta):
            raise ValueError(
                "La jornada de esta venta ya tiene corte de caja; solo es posible consultarla."
            )

        ####################################################
        # REGRESAR INVENTARIO
        ####################################################

        for detalle in venta.detalles:

            producto = Producto.query.get(detalle.producto_id)

            if not producto:
                continue

            if not mover_inventario(
                producto_id=producto.id,
                unidad_id=venta.unidad_negocio_id,
                cantidad=detalle.cantidad,
                tipo="DEVOLUCION_ENTRADA",
                usuario_id=current_user.id,
                referencia=venta.numero_venta,
                observaciones=f"Cancelación de venta {venta.numero_venta}"
            ):
                raise ValueError(
                    f"No fue posible regresar inventario de {producto.nombre}"
                )

            producto.stock = stock_producto(
                producto.id,
                venta.unidad_negocio_id
            )

        ####################################################
        # QUITAR PUNTOS
        ####################################################
        if venta.cliente_id and venta.puntos_otorgados > 0:

            cliente = Cliente.query.get(venta.cliente_id)

            if cliente:

                cliente.puntos = max(
                    0,
                    cliente.puntos - venta.puntos_otorgados
                )

        ####################################################
        # MOVIMIENTO DE CAJA
        ####################################################

        caja_venta = caja_de_venta(venta)

        movimiento = MovimientoCaja(

            caja_id=caja_venta.id if caja_venta else None,

            tipo="CANCELACION_VENTA",

            origen_id=venta.id,

            monto=-venta.total,

            usuario_id=current_user.id,

            observaciones=f"Cancelación de venta {venta.numero_venta}"

        )

        db.session.add(movimiento)

        if caja_venta and venta.metodo_pago == "EFECTIVO":
            caja_venta.saldo_actual = (caja_venta.saldo_actual or 0) - venta.total

        registrar_auditoria(
            "VENTAS", "CANCELAR",
            f"{venta.numero_venta} por ${venta.total:.2f}"
        )

        ####################################################
        # ACTUALIZAR VENTA
        ####################################################

        venta.estado = "CANCELADA"

        venta.cancelada = True

        venta.fecha_cancelacion = datetime.now()

        venta.usuario_cancelacion_id = current_user.id

        db.session.commit()

        flash(
            f"Venta {venta.numero_venta} cancelada correctamente.",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(str(e), "danger")

    return redirect(url_for("detalle_venta", id=venta.id))

###############################################################
# VENTAS
###############################################################


# DUPLICADO ventas ELIMINADO

@app.route("/ventas/<int:id>")
@login_required
@modulo_requerido("VENTAS")
def detalle_venta(id):

    venta = Venta.query.get_or_404(id)

    validar_unidad_registro(venta)

    return render_template(
        "detalle_venta.html",
        venta=venta
    )


@app.route("/ventas/nueva", methods=["GET", "POST"])
@login_required
@modulo_requerido("VENTAS")
def nueva_venta():

    productos_db = (
        Producto.query
        .filter(
            Producto.unidad_negocio_id == current_user.unidad_negocio_id,
            Producto.activo == True
        )
        .order_by(Producto.nombre)
        .all()
    )

    clientes_db = Cliente.query.filter(
        Cliente.unidad_negocio_id == current_user.unidad_negocio_id,
        Cliente.activo == True
    ).order_by(Cliente.nombre).all()

    config = Configuracion.query.filter_by(
        unidad_negocio_id=current_user.unidad_negocio_id
    ).first()

    if not config:
        config = Configuracion(unidad_negocio_id=current_user.unidad_negocio_id)
        db.session.add(config)
        db.session.commit()

    if request.method == "GET":

        productos = [
            {
                "id": p.id,
                "codigo": p.codigo,
                "nombre": p.nombre,
                "talla": p.talla,
                "color": p.color,
                "precio": float(p.precio or 0),
                "imagen": p.imagen,
                "stock_real": stock_producto(p.id, p.unidad_negocio_id),
            }
            for p in productos_db
        ]
        clientes = [
            {"id": c.id, "nombre": c.nombre, "puntos": c.puntos or 0}
            for c in clientes_db
        ]
        config_js = {
            campo: getattr(config, campo)
            for campo in (
                "mayoreo_activo", "descuento_3_5", "descuento_6_10",
                "descuento_11_mas", "descuento_adicional_activo",
                "descuento_adicional_porcentaje", "fidelidad_activa",
                "porcentaje_fidelidad",
            )
        }

        return render_template(
            "nueva_venta.html",
            productos=productos,
            clientes=clientes,
            config=config_js
        )

    unidad_id = current_user.unidad_negocio_id

    caja = Caja.query.filter_by(
        unidad_negocio_id=unidad_id,
        abierta=True
    ).first()

    if not caja:
        if es_gerente_caja():
            flash("Abre la caja antes de registrar ventas.", "warning")
            return redirect(url_for("abrir_caja"))
        flash(
            "La caja está cerrada. El gerente debe abrir la jornada para vender.",
            "warning"
        )
        return redirect(url_for("caja"))

    try:

        try:
            carrito = json.loads(request.form.get("carrito") or "[]")
        except ValueError:
            carrito = []

        if not carrito:
            raise ValueError("Agrega al menos un producto.")

        permitidos = {p.id: p for p in productos_db}

        cantidades = {}
        for item in carrito:
            pid = int(item.get("producto_id"))
            cant = int(item.get("cantidad"))
            if pid not in permitidos or cant <= 0:
                raise ValueError("Producto inválido en la venta.")
            cantidades[pid] = cantidades.get(pid, 0) + cant

        cliente = None
        cliente_id = request.form.get("cliente_id", type=int)
        if cliente_id:
            cliente = next((c for c in clientes_db if c.id == cliente_id), None)
            if not cliente:
                raise ValueError("Cliente inválido.")

        metodo = request.form.get("metodo_pago", "EFECTIVO")
        if metodo not in ("EFECTIVO", "TARJETA", "TRANSFERENCIA"):
            raise ValueError("Método de pago inválido.")

        subtotal = sum(
            permitidos[pid].precio * cant for pid, cant in cantidades.items()
        )
        piezas = sum(cantidades.values())

        descuento_mayoreo = 0
        if request.form.get("mayoreo") and config.mayoreo_activo:
            if piezas >= 11:
                descuento_mayoreo = subtotal * config.descuento_11_mas / 100
            elif piezas >= 6:
                descuento_mayoreo = subtotal * config.descuento_6_10 / 100
            elif piezas >= 3:
                descuento_mayoreo = subtotal * config.descuento_3_5 / 100

        base = subtotal - descuento_mayoreo

        descuento_adicional = 0
        if request.form.get("desc_adicional") and config.descuento_adicional_activo:
            descuento_adicional = base * config.descuento_adicional_porcentaje / 100

        base -= descuento_adicional

        descuento_fidelidad = 0
        if request.form.get("desc_fidelidad") and config.fidelidad_activa:
            descuento_fidelidad = base * config.porcentaje_fidelidad / 100

        descuento = descuento_mayoreo + descuento_adicional + descuento_fidelidad
        total = round(subtotal - descuento, 2)

        venta = Venta(
            numero_venta=generar_numero_venta(),
            cliente_id=cliente.id if cliente else None,
            unidad_negocio_id=unidad_id,
            usuario_id=current_user.id,
            subtotal=subtotal,
            descuento=descuento,
            total=total,
            metodo_pago=metodo,
            estado="ACTIVA"
        )
        db.session.add(venta)
        db.session.flush()

        for pid, cant in cantidades.items():
            producto = permitidos[pid]

            if not mover_inventario(
                producto_id=pid,
                unidad_id=unidad_id,
                cantidad=cant,
                tipo="VENTA",
                usuario_id=current_user.id,
                referencia=venta.numero_venta,
                observaciones="Venta"
            ):
                raise ValueError(
                    f"No hay existencias suficientes de {producto.nombre}."
                )

            producto.stock = stock_producto(pid, unidad_id)

            db.session.add(DetalleVenta(
                venta_id=venta.id,
                producto_id=pid,
                cantidad=cant,
                precio_unitario=producto.precio,
                subtotal=producto.precio * cant
            ))

        if cliente and config.fidelidad_activa and config.puntos_por_peso:
            puntos = int(total / config.puntos_por_peso)
            if puntos > 0:
                cliente.puntos = (cliente.puntos or 0) + puntos
                venta.puntos_otorgados = puntos
                db.session.add(MovimientoPuntos(
                    cliente_id=cliente.id,
                    puntos=puntos,
                    tipo="VENTA",
                    usuario_id=current_user.id,
                    observaciones=venta.numero_venta
                ))

        db.session.add(MovimientoCaja(
            caja_id=caja.id,
            tipo="VENTA",
            origen_id=venta.id,
            monto=total,
            usuario_id=current_user.id,
            observaciones=f"Venta {venta.numero_venta} ({metodo})"
        ))

        if metodo == "EFECTIVO":
            caja.saldo_actual = (caja.saldo_actual or 0) + total

        registrar_auditoria("VENTAS", "CREAR", venta.numero_venta)

        db.session.commit()

        flash(f"Venta {venta.numero_venta} registrada.", "success")

        return redirect(url_for("detalle_venta", id=venta.id))

    except Exception as e:

        db.session.rollback()

        flash(str(e), "danger")

        return redirect(url_for("nueva_venta"))


###############################################################
# VENTAS
###############################################################

@app.route("/ventas")
@login_required
@modulo_requerido("VENTAS")
def ventas():

    ventas = (
        filtro_unidad(Venta.query, Venta)
        .order_by(Venta.fecha.desc())
        .all()
    )

    return render_template(
        "ventas.html",
        ventas=ventas
    )

###############################################################
# COMPRAS
###############################################################

@app.route("/compras")
@login_required
@modulo_requerido("COMPRAS")
def compras():

    compras = (
        filtro_unidad(
            Compra.query,
            Compra
        )
        .order_by(
            Compra.fecha.desc()
        )
        .all()
    )

    return render_template(
        "compras.html",
        compras=compras
    )


@app.route("/compras/<int:id>")
@login_required
@modulo_requerido("COMPRAS")
def detalle_compra(id):

    compra = Compra.query.get_or_404(id)

    validar_unidad_registro(compra)

    return render_template(
        "detalle_compra.html",
        compra=compra
    )

###############################################################
# NUEVA COMPRA
###############################################################

@app.route("/compras/nueva", methods=["GET", "POST"])
@login_required
@modulo_requerido("COMPRAS")
def nueva_compra():

    proveedores = filtro_unidad(
        Proveedor.query,
        Proveedor
    ).order_by(
        Proveedor.nombre
    ).all()

    productos = filtro_unidad(
        Producto.query,
        Producto
    ).filter(
        Producto.activo == True
    ).order_by(
        Producto.nombre
    ).all()

    unidades_query = UnidadNegocio.query.filter_by(activa=True)
    if not current_user.administrador_principal:
        unidades_query = unidades_query.filter(
            UnidadNegocio.id == current_user.unidad_negocio_id
        )
    unidades = unidades_query.order_by(
        UnidadNegocio.nombre
    ).all()

    if request.method == "POST":

        try:

            proveedor_id = int(
                request.form["proveedor_id"]
            )

            unidad_negocio_id = int(
                request.form["unidad_negocio_id"]
            )

            carrito = json.loads(
                request.form["carrito"]
            )

            if not carrito:

                raise ValueError(
                    "Debe agregar productos."
                )

            if unidad_negocio_id not in {u.id for u in unidades}:
                abort(403)

            if proveedor_id not in {p.id for p in proveedores}:
                abort(403)

            compra = Compra(

                numero_compra=generar_numero_compra(),

                proveedor_id=proveedor_id,

                unidad_negocio_id=unidad_negocio_id,

                usuario_id=current_user.id,

                total=0

            )

            db.session.add(compra)

            db.session.flush()

            total = 0

            ###################################################
            # RECORRER PRODUCTOS
            ###################################################

            for item in carrito:

                producto = filtro_unidad(
                    Producto.query.with_for_update(),
                    Producto
                ).filter_by(
                    id=item["producto_id"]
                ).first()

                if not producto:

                    raise ValueError(
                        "El producto no pertenece a la unidad de negocio."
                    )

                cantidad = int(item["cantidad"])

                costo = float(item["costo"])

                subtotal = cantidad * costo

                detalle = DetalleCompra(

                    compra_id=compra.id,

                    producto_id=producto.id,

                    cantidad=cantidad,

                    precio_unitario=costo,

                    subtotal=subtotal

                )

                db.session.add(detalle)

                ###################################################
                # INVENTARIO
                ###################################################

                if not mover_inventario(

                    producto_id=producto.id,

                    unidad_id=compra.unidad_negocio_id,

                    cantidad=cantidad,

                    tipo="COMPRA",

                    usuario_id=current_user.id,

                    referencia=compra.numero_compra,

                    observaciones=f"Compra {compra.numero_compra}"

                ):

                    raise ValueError(

                        f"No fue posible actualizar inventario de {producto.nombre}"

                    )

                ###################################################
                # SINCRONIZAR STOCK GENERAL
                ###################################################

                producto.stock = stock_producto(

                    producto.id,

                    compra.unidad_negocio_id

                )

                ###################################################
                # COSTO PROMEDIO
                ###################################################

                inventario = obtener_inventario(

                    producto.id,

                    compra.unidad_negocio_id

                )

                existencia = inventario.existencia

                if existencia > 0:

                    producto.costo_promedio = (

                        (
                            producto.costo_promedio *
                            max(existencia - cantidad, 0)
                        )

                        +

                        (cantidad * costo)

                    ) / existencia

                total += subtotal

            ###################################################
            # TOTAL DE LA COMPRA
            ###################################################

            compra.total = total

            ###################################################
            # AUDITORÍA
            ###################################################

            registrar_auditoria(

                "COMPRAS",

                "NUEVA",

                compra.numero_compra

            )

            ###################################################
            # GUARDAR
            ###################################################

            db.session.commit()

            flash(
                f"Compra {compra.numero_compra} registrada correctamente.",
                "success"
            )

            return redirect(
                url_for(
                    "detalle_compra",
                    id=compra.id
                )
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    ###################################################
    # GET
    ###################################################

    productos_data = []

    for p in productos:

        productos_data.append({

            "id": p.id,

            "codigo": p.codigo,

            "nombre": p.nombre,

            "precio": p.precio,

            "costo_promedio": p.costo_promedio,

            "stock": stock_producto(
                p.id,
                current_user.unidad_negocio_id
            ),

            "imagen": p.imagen,

            "unidad_negocio_id": p.unidad_negocio_id,

            "unidad_negocio": {
                "nombre": p.unidad.nombre if p.unidad else ""
            },

            "talla": p.talla,

            "color": p.color

        })

    proveedores_json = [

        {

            "id": proveedor.id,

            "nombre": proveedor.nombre

        }

        for proveedor in proveedores

    ]

    return render_template(

        "nueva_compra.html",

        productos=productos_data,

        proveedores=proveedores_json,

        unidades=unidades

    )

###############################################################
# CANCELAR COMPRA
###############################################################

@app.route("/compras/cancelar/<int:id>", methods=["POST"])
@login_required
@modulo_requerido("COMPRAS")
def cancelar_compra(id):

    if current_user.rol != "ADMIN":

        flash(
            "Solo un administrador puede cancelar compras.",
            "danger"
        )

        return redirect(url_for("compras"))

    compra = Compra.query.get_or_404(id)

    validar_unidad_registro(compra)

    if compra.estado == "CANCELADA":

        flash(
            "La compra ya fue cancelada.",
            "warning"
        )

        return redirect(url_for("detalle_compra", id=id))

    try:

        for detalle in compra.detalles:

            producto = Producto.query.get(detalle.producto_id)

            if not producto:
                continue

            inventario = obtener_inventario(
                producto.id,
                compra.unidad_negocio_id
            )

            if inventario.existencia < detalle.cantidad:

                raise ValueError(
                    f"No es posible cancelar la compra porque ya no existe suficiente inventario de {producto.nombre}."
                )

            inventario.existencia -= detalle.cantidad

            registrar_movimiento(

                producto_id=producto.id,

                unidad_id=compra.unidad_negocio_id,

                tipo="DEVOLUCION_PROVEEDOR",

                cantidad=detalle.cantidad,

                usuario_id=current_user.id,

                referencia=compra.numero_compra,

                observaciones="Cancelación de compra"

            )

            producto.stock = stock_producto(
                producto.id,
                compra.unidad_negocio_id
            )

        compra.estado = "CANCELADA"

        registrar_auditoria(

            "COMPRAS",

            "CANCELAR",

            compra.numero_compra

        )

        db.session.commit()

        flash(
            "Compra cancelada correctamente.",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(
            str(e),
            "danger"
        )

    return redirect(
        url_for(
            "detalle_compra",
            id=id
        )
    )

###############################################################
# PROVEEDORES
###############################################################

@app.route("/proveedores")
@login_required
@modulo_requerido("PROVEEDORES")
def proveedores():

    proveedores = (
        filtro_unidad(
            Proveedor.query,
            Proveedor
        )
        .order_by(
            Proveedor.nombre
        )
        .all()
    )

    return render_template(
        "proveedores.html",
        proveedores=proveedores
    )


@app.route("/proveedores/nuevo", methods=["GET", "POST"])
@login_required
@modulo_requerido("PROVEEDORES")
def nuevo_proveedor():

    if request.method == "POST":

        try:

            proveedor = Proveedor(

                nombre=request.form["nombre"].strip(),

                telefono=request.form.get("telefono"),

                correo=request.form.get("correo"),

                direccion=request.form.get("direccion"),

                contacto=request.form.get("contacto"),

                unidad_negocio_id=current_user.unidad_negocio_id,

                activo=True

            )

            db.session.add(proveedor)

            registrar_auditoria(

                "PROVEEDORES",

                "NUEVO",

                proveedor.nombre

            )

            db.session.commit()

            flash(
                "Proveedor registrado correctamente.",
                "success"
            )

            return redirect(
                url_for("proveedores")
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    return render_template(
        "nuevo_proveedor.html"
    )

###############################################################
# EDITAR PROVEEDOR
###############################################################

@app.route("/proveedores/editar/<int:id>", methods=["GET", "POST"])
@login_required
@modulo_requerido("PROVEEDORES")
def editar_proveedor(id):

    proveedor = Proveedor.query.get_or_404(id)

    validar_unidad_registro(proveedor)

    if request.method == "POST":

        try:

            proveedor.nombre = request.form["nombre"].strip()

            proveedor.telefono = request.form.get("telefono")

            proveedor.correo = request.form.get("correo")

            proveedor.direccion = request.form.get("direccion")

            proveedor.contacto = request.form.get("contacto")

            proveedor.activo = "activo" in request.form

            registrar_auditoria(

                "PROVEEDORES",

                "EDITAR",

                proveedor.nombre

            )

            db.session.commit()

            flash(
                "Proveedor actualizado correctamente.",
                "success"
            )

            return redirect(
                url_for("proveedores")
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    return render_template(

        "editar_proveedor.html",

        proveedor=proveedor

    )

###############################################################
# ELIMINAR PROVEEDOR
###############################################################

@app.route("/proveedores/eliminar/<int:id>", methods=["POST"])
@login_required
@modulo_requerido("PROVEEDORES")
def eliminar_proveedor(id):

    proveedor = Proveedor.query.get_or_404(id)

    validar_unidad_registro(proveedor)

    try:

        # Desactivación lógica
        proveedor.activo = False

        registrar_auditoria(

            "PROVEEDORES",

            "ELIMINAR",

            proveedor.nombre

        )

        db.session.commit()

        flash(
            "Proveedor desactivado correctamente.",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(
            str(e),
            "danger"
        )

    return redirect(
        url_for("proveedores")
    )

###############################################################
# DETALLE DEL PROVEEDOR
###############################################################

@app.route("/proveedores/<int:id>")
@login_required
@modulo_requerido("PROVEEDORES")
def detalle_proveedor(id):

    proveedor = Proveedor.query.get_or_404(id)

    validar_unidad_registro(proveedor)

    compras = (
        Compra.query
        .filter_by(
            proveedor_id=proveedor.id
        )
        .order_by(
            Compra.fecha.desc()
        )
        .all()
    )

    total_compras = sum(
        compra.total for compra in compras
    )

    total_documentos = len(compras)

    ultima_compra = None

    if compras:
        ultima_compra = compras[0].fecha

    return render_template(

        "detalle_proveedor.html",

        proveedor=proveedor,

        compras=compras,

        total_compras=total_compras,

        total_documentos=total_documentos,

        ultima_compra=ultima_compra

    )

###############################################################
# CLIENTES
###############################################################

@app.route("/clientes")
@login_required
@modulo_requerido("CLIENTES")
def clientes():

    clientes = (
        filtro_unidad(
            Cliente.query,
            Cliente
        )
        .order_by(
            Cliente.nombre
        )
        .all()
    )

    return render_template(
        "clientes.html",
        clientes=clientes
    )


###############################################################
# NUEVO CLIENTE
###############################################################

@app.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
@modulo_requerido("CLIENTES")
def nuevo_cliente():

    if request.method == "POST":

        try:

            cliente = Cliente(

                nombre=request.form["nombre"].strip(),

                telefono=request.form.get("telefono"),

                correo=request.form.get("correo"),

                direccion=request.form.get("direccion"),

                rfc=request.form.get("rfc"),

                puntos=0,

                activo=True,

                unidad_negocio_id=current_user.unidad_negocio_id

            )

            db.session.add(cliente)

            registrar_auditoria(

                "CLIENTES",

                "NUEVO",

                cliente.nombre

            )

            db.session.commit()

            flash(
                "Cliente registrado correctamente.",
                "success"
            )

            return redirect(
                url_for("clientes")
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    return render_template(
        "nuevo_cliente.html"
    )

###############################################################
# EDITAR CLIENTE
###############################################################

@app.route("/clientes/editar/<int:id>", methods=["GET", "POST"])
@login_required
@modulo_requerido("CLIENTES")
def editar_cliente(id):

    cliente = Cliente.query.get_or_404(id)

    validar_unidad_registro(cliente)

    if request.method == "POST":

        try:

            cliente.nombre = request.form["nombre"].strip()
            cliente.telefono = request.form.get("telefono")
            cliente.correo = request.form.get("correo")
            cliente.direccion = request.form.get("direccion")
            cliente.rfc = request.form.get("rfc")
            cliente.activo = "activo" in request.form

            registrar_auditoria(
                "CLIENTES",
                "EDITAR",
                cliente.nombre
            )

            db.session.commit()

            flash(
                "Cliente actualizado correctamente.",
                "success"
            )

            return redirect(url_for("clientes"))

        except Exception as e:

            db.session.rollback()

            flash(str(e), "danger")

    return render_template(
        "editar_cliente.html",
        cliente=cliente
    )


###############################################################
# ELIMINAR CLIENTE
###############################################################

@app.route("/clientes/eliminar/<int:id>", methods=["POST"])
@login_required
@modulo_requerido("CLIENTES")
def eliminar_cliente(id):

    cliente = Cliente.query.get_or_404(id)

    validar_unidad_registro(cliente)

    try:

        cliente.activo = False

        registrar_auditoria(
            "CLIENTES",
            "ELIMINAR",
            cliente.nombre
        )

        db.session.commit()

        flash(
            "Cliente desactivado correctamente.",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(str(e), "danger")

    return redirect(url_for("clientes"))

###############################################################
# DETALLE DEL CLIENTE
###############################################################

@app.route("/clientes/<int:id>")
@login_required
@modulo_requerido("CLIENTES")
def detalle_cliente(id):

    cliente = Cliente.query.get_or_404(id)

    validar_unidad_registro(cliente)

    ###################################################
    # HISTORIAL DE VENTAS
    ###################################################

    ventas = (
        Venta.query
        .filter_by(cliente_id=cliente.id)
        .order_by(Venta.fecha.desc())
        .all()
    )

    ###################################################
    # HISTORIAL DE APARTADOS
    ###################################################

    apartados = (
        Apartado.query
        .filter_by(cliente_id=cliente.id)
        .order_by(Apartado.fecha.desc())
        .all()
    )

    ###################################################
    # CRÉDITOS DEL CLIENTE
    ###################################################

    creditos = (
        CreditoCliente.query
        .filter_by(cliente_id=cliente.id)
        .order_by(CreditoCliente.fecha.desc())
        .all()
    )

    ###################################################
    # PAGOS DE CRÉDITO
    ###################################################

    pagos_credito = (
        PagoCredito.query
        .filter_by(cliente_id=cliente.id)
        .order_by(PagoCredito.fecha.desc())
        .all()
    )

    ###################################################
    # TOTALES
    ###################################################

    total_compras = sum(
        venta.total
        for venta in ventas
        if venta.estado == "ACTIVA"
    )

    total_apartados = sum(
        apartado.total
        for apartado in apartados
        if apartado.estado != "CANCELADO"
    )

    saldo_creditos = sum(
        credito.saldo
        for credito in creditos
    )

    return render_template(

        "detalle_cliente.html",

        cliente=cliente,

        ventas=ventas,

        apartados=apartados,

        creditos=creditos,

        pagos_credito=pagos_credito,

        total_compras=total_compras,

        total_apartados=total_apartados,

        saldo_creditos=saldo_creditos

    )

###############################################################
# BUSCAR CLIENTES
###############################################################

@app.route("/clientes/buscar")
@login_required
@modulo_requerido("CLIENTES")
def buscar_clientes():

    texto = request.args.get("q", "").strip()

    consulta = filtro_unidad(
        Cliente.query,
        Cliente
    )

    if texto:

        consulta = consulta.filter(

            db.or_(

                Cliente.nombre.ilike(f"%{texto}%"),

                Cliente.telefono.ilike(f"%{texto}%"),

                Cliente.correo.ilike(f"%{texto}%"),

                Cliente.rfc.ilike(f"%{texto}%")

            )

        )

    clientes = consulta.order_by(
        Cliente.nombre
    ).all()

    return render_template(

        "clientes.html",

        clientes=clientes,

        busqueda=texto

    )

###############################################################
# HISTORIAL DE PUNTOS
###############################################################

@app.route("/clientes/<int:id>/puntos")
@login_required
@modulo_requerido("CLIENTES")
def historial_puntos(id):

    cliente = Cliente.query.get_or_404(id)

    validar_unidad_registro(cliente)

    movimientos = (
        MovimientoPuntos.query
        .filter_by(cliente_id=cliente.id)
        .order_by(MovimientoPuntos.fecha.desc())
        .all()
    )

    return render_template(

        "historial_puntos.html",

        cliente=cliente,

        movimientos=movimientos

    )


###############################################################
# AJUSTE MANUAL DE PUNTOS
###############################################################

@app.route("/clientes/<int:id>/ajustar_puntos", methods=["POST"])
@login_required
@modulo_requerido("CLIENTES")
def ajustar_puntos(id):

    if current_user.rol != "ADMIN":

        flash(
            "Solo un administrador puede modificar puntos.",
            "danger"
        )

        return redirect(
            url_for("detalle_cliente", id=id)
        )

    cliente = Cliente.query.get_or_404(id)

    validar_unidad_registro(cliente)

    try:

        puntos = int(request.form["puntos"])

        motivo = request.form.get(
            "motivo",
            "Ajuste manual"
        )

        cliente.puntos += puntos

        if cliente.puntos < 0:
            cliente.puntos = 0

        movimiento = MovimientoPuntos(

            cliente_id=cliente.id,

            puntos=puntos,

            tipo="AJUSTE",

            usuario_id=current_user.id,

            observaciones=motivo

        )

        db.session.add(movimiento)

        registrar_auditoria(

            "CLIENTES",

            "AJUSTE_PUNTOS",

            cliente.nombre

        )

        db.session.commit()

        flash(
            "Puntos actualizados correctamente.",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(
            str(e),
            "danger"
        )

    return redirect(
        url_for(
            "historial_puntos",
            id=id
        )
    )

###############################################################
# CAJA
###############################################################

ROLES_GERENTE_CAJA = {"ADMIN", "GERENTE_EMPRESA", "GERENTE_UNIDAD"}


def es_gerente_caja():
    return bool(
        getattr(current_user, "administrador_principal", False)
        or current_user.rol in ROLES_GERENTE_CAJA
    )


def unidades_caja_visibles():
    if getattr(current_user, "administrador_principal", False):
        return UnidadNegocio.query.order_by(UnidadNegocio.nombre).all()
    if current_user.unidad_negocio_id is None and current_user.empresa_id:
        return UnidadNegocio.query.filter_by(
            empresa_id=current_user.empresa_id
        ).order_by(UnidadNegocio.nombre).all()
    if current_user.unidad_negocio_id:
        unidad = UnidadNegocio.query.get(current_user.unidad_negocio_id)
        return [unidad] if unidad else []
    return []


def caja_de_venta(venta):
    mov = MovimientoCaja.query.filter_by(
        tipo="VENTA", origen_id=venta.id
    ).first()
    return mov.caja if mov and mov.caja_id else None


def venta_en_caja_cerrada(venta):
    caja_venta = caja_de_venta(venta)
    return caja_venta is not None and not caja_venta.abierta


def resumen_caja(caja):
    movs = MovimientoCaja.query.filter_by(
        caja_id=caja.id
    ).order_by(MovimientoCaja.fecha).all()
    ids = [m.origen_id for m in movs if m.tipo == "VENTA" and m.origen_id]
    ventas = Venta.query.filter(
        Venta.id.in_(ids)
    ).order_by(Venta.fecha).all() if ids else []
    activas = [v for v in ventas if v.estado == "ACTIVA"]
    canceladas = [v for v in ventas if v.estado != "ACTIVA"]
    por_metodo = {}
    for v in activas:
        clave = v.metodo_pago or "-"
        por_metodo[clave] = por_metodo.get(clave, 0) + (v.total or 0)
    fin = caja.fecha_cierre or datetime.now()
    apartados = Apartado.query.filter(
        Apartado.unidad_negocio_id == caja.unidad_negocio_id,
        Apartado.fecha >= caja.fecha_apertura,
        Apartado.fecha <= fin
    ).order_by(Apartado.fecha).all()
    return {
        "movimientos": list(reversed(movs)),
        "ventas": ventas,
        "activas": activas,
        "canceladas": canceladas,
        "total_ventas": sum(v.total or 0 for v in activas),
        "total_cancelado": sum(v.total or 0 for v in canceladas),
        "por_metodo": por_metodo,
        "entradas": sum(m.monto or 0 for m in movs if m.tipo == "ENTRADA"),
        "salidas": sum(m.monto or 0 for m in movs if m.tipo == "SALIDA"),
        "apartados": apartados,
        "esperado": caja.saldo_actual or 0,
    }


def meses_historial_caja_usuario(usuario=None):
    """Meses de historial de caja visibles; None significa sin límite."""
    usuario = usuario or current_user
    if getattr(usuario, "administrador_principal", False):
        return None
    if usuario.meses_historial_caja:
        return usuario.meses_historial_caja
    return 3 if usuario.rol in ROLES_GERENTE_CAJA else 2


def fecha_limite_historial():
    meses = meses_historial_caja_usuario()
    return None if meses is None else datetime.now() - timedelta(days=30 * meses)


def _solo_principal():
    if not getattr(current_user, "administrador_principal", False):
        abort(403)


EXTENSIONES_LOGO = {"png", "jpg", "jpeg", "gif", "webp"}


def _guardar_logo(archivo, prefijo, id_):
    nombre = secure_filename(archivo.filename or "")
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if extension not in EXTENSIONES_LOGO:
        raise ValueError("Formato no permitido. Usa PNG, JPG, GIF o WEBP.")
    carpeta = os.path.join(UPLOAD_FOLDER, "logos")
    os.makedirs(carpeta, exist_ok=True)
    final = f"{prefijo}_{id_}_{uuid.uuid4().hex[:8]}.{extension}"
    archivo.save(os.path.join(carpeta, final))
    return final


@app.route("/logotipos", methods=["GET", "POST"])
@login_required
def logos_admin():

    _solo_principal()

    if request.method == "POST":
        tipo = request.form.get("tipo")
        registro_id = request.form.get("id", type=int)
        modelo = {"empresa": Empresa, "unidad": UnidadNegocio}.get(tipo)
        archivo = request.files.get("logo")
        if not modelo or not registro_id:
            abort(400)
        registro = modelo.query.get_or_404(registro_id)
        try:
            if request.form.get("quitar"):
                registro.logo = None
            elif archivo and archivo.filename:
                registro.logo = _guardar_logo(archivo, tipo, registro.id)
            else:
                raise ValueError("Selecciona una imagen.")
            registrar_auditoria("CONFIGURACION", "LOGO", f"{tipo} {registro.id}")
            db.session.commit()
            flash("Logotipo actualizado.", "success")
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
        return redirect(url_for("logos_admin"))

    return render_template(
        "logos_admin.html",
        empresas=Empresa.query.order_by(Empresa.nombre).all()
    )


@app.route("/caja/retencion", methods=["GET", "POST"])
@login_required
def retencion_historial():

    _solo_principal()

    if request.method == "POST":
        usuario = Usuario.query.get_or_404(request.form.get("usuario_id", type=int))
        meses = request.form.get("meses", type=int)
        if meses is not None and meses < 1:
            flash("Indica un número de meses mayor a cero.", "danger")
        else:
            usuario.meses_historial_caja = meses
            registrar_auditoria(
                "CAJA", "RETENCION_HISTORIAL",
                f"{usuario.usuario}: {meses or 'predeterminado'} meses"
            )
            db.session.commit()
            flash("Vigencia del historial actualizada.", "success")
        return redirect(url_for("retencion_historial"))

    usuarios = Usuario.query.filter_by(
        administrador_principal=False
    ).order_by(Usuario.empresa_id, Usuario.nombre).all()

    return render_template(
        "retencion_historial.html",
        usuarios=[(u, meses_historial_caja_usuario(u)) for u in usuarios]
    )


@app.route("/caja/historial/exportar")
@login_required
@modulo_requerido("CAJA")
def exportar_historial_caja():

    _solo_principal()

    import csv
    import io

    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow([
        "Jornada", "Empresa", "Sucursal", "Apertura", "Cierre", "Estado",
        "Saldo inicial", "Ventas activas", "Ventas canceladas",
        "Esperado", "Contado", "Diferencia", "Abrió"
    ])

    consulta = Caja.query.order_by(Caja.fecha_apertura)
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    try:
        if desde:
            consulta = consulta.filter(
                Caja.fecha_apertura >= datetime.strptime(desde, "%Y-%m-%d")
            )
        if hasta:
            consulta = consulta.filter(
                Caja.fecha_apertura < datetime.strptime(hasta, "%Y-%m-%d") + timedelta(days=1)
            )
    except ValueError:
        abort(400)

    for c in consulta.all():
        r = resumen_caja(c)
        unidad = c.unidad
        escritor.writerow([
            c.id,
            unidad.empresa.nombre if unidad and unidad.empresa else "",
            unidad.nombre if unidad else "",
            c.fecha_apertura.strftime("%Y-%m-%d %H:%M"),
            c.fecha_cierre.strftime("%Y-%m-%d %H:%M") if c.fecha_cierre else "",
            "Abierta" if c.abierta else "Cerrada",
            f"{c.fondo_inicial or 0:.2f}",
            f"{r['total_ventas']:.2f}",
            f"{r['total_cancelado']:.2f}",
            f"{r['esperado']:.2f}",
            "" if c.abierta else f"{c.efectivo_final or 0:.2f}",
            "" if c.abierta else f"{c.diferencia or 0:.2f}",
            c.usuario.nombre if c.usuario else "",
        ])

    registrar_auditoria("CAJA", "EXPORTAR_HISTORIAL", f"{desde or '-'} a {hasta or '-'}")
    db.session.commit()

    from flask import Response
    return Response(
        "\ufeff" + salida.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=historial_caja.csv"}
    )


@app.route("/caja/historial")
@login_required
@modulo_requerido("CAJA")
def caja_historial():

    unidades = unidades_caja_visibles()
    permitidas = {u.id for u in unidades}
    unidad_id = request.args.get("unidad_id", type=int)
    if unidad_id and unidad_id not in permitidas:
        abort(403)

    consulta = Caja.query.filter(
        Caja.unidad_negocio_id.in_(
            [unidad_id] if unidad_id else (permitidas or [0])
        )
    )
    limite = fecha_limite_historial()
    if limite:
        consulta = consulta.filter(Caja.fecha_apertura >= limite)
    consulta = consulta.order_by(Caja.fecha_apertura.desc()).limit(200)

    jornadas = []
    consolidado = {}
    for caja_item in consulta.all():
        resumen = resumen_caja(caja_item)
        jornadas.append((caja_item, resumen))
        fila = consolidado.setdefault(
            caja_item.unidad.nombre if caja_item.unidad else "-",
            {"jornadas": 0, "ventas": 0, "esperado": 0, "diferencia": 0}
        )
        fila["jornadas"] += 1
        fila["ventas"] += resumen["total_ventas"]
        fila["esperado"] += resumen["esperado"]
        fila["diferencia"] += (caja_item.diferencia or 0) if not caja_item.abierta else 0

    return render_template(
        "caja_historial.html",
        jornadas=jornadas,
        consolidado=consolidado,
        unidades=unidades,
        unidad_id=unidad_id,
        es_gerente=es_gerente_caja()
    )


@app.route("/caja/jornada/<int:id>")
@login_required
@modulo_requerido("CAJA")
def detalle_caja(id):

    caja_item = Caja.query.get_or_404(id)

    limite = fecha_limite_historial()
    if limite and not caja_item.abierta and caja_item.fecha_apertura < limite:
        abort(403)
    if caja_item.unidad_negocio_id not in {
        u.id for u in unidades_caja_visibles()
    }:
        abort(403)

    return render_template(
        "detalle_caja.html",
        caja=caja_item,
        resumen=resumen_caja(caja_item),
        es_gerente=es_gerente_caja()
    )


@app.route("/caja")
@login_required
@modulo_requerido("CAJA")
def caja():

    caja = Caja.query.filter_by(

        unidad_negocio_id=current_user.unidad_negocio_id,

        abierta=True

    ).first()

    movimientos = []

    saldo = 0

    if caja:

        movimientos = (

            MovimientoCaja.query

            .filter_by(

                caja_id=caja.id

            )

            .order_by(

                MovimientoCaja.fecha.desc()

            )

            .all()

        )

        saldo = caja.saldo_actual

    ultima = None

    if not caja:

        ultima = Caja.query.filter_by(
            unidad_negocio_id=current_user.unidad_negocio_id,
            abierta=False
        ).order_by(Caja.fecha_cierre.desc()).first()

    return render_template(

        "caja.html",

        caja=caja,

        ultima=ultima,

        resumen=resumen_caja(caja) if caja else None,

        es_gerente=es_gerente_caja(),

        movimientos=movimientos,

        saldo=saldo

    )


###############################################################
# ABRIR CAJA
###############################################################

@app.route("/caja/abrir", methods=["GET", "POST"])
@login_required
@modulo_requerido("CAJA")
def abrir_caja():

    if not es_gerente_caja():

        flash(
            "Solo el gerente puede abrir la caja e indicar el saldo inicial.",
            "danger"
        )

        return redirect(url_for("caja"))

    caja_abierta = Caja.query.filter_by(

        unidad_negocio_id=current_user.unidad_negocio_id,

        abierta=True

    ).first()

    if caja_abierta:

        flash(

            "Ya existe una caja abierta.",

            "warning"

        )

        return redirect(

            url_for("caja")

        )

    if request.method == "POST":

        try:

            fondo = float(

                request.form["fondo_inicial"]

            )

            caja = Caja(

                unidad_negocio_id=current_user.unidad_negocio_id,

                usuario_id=current_user.id,

                fondo_inicial=fondo,

                saldo_actual=fondo,

                abierta=True

            )

            db.session.add(caja)

            db.session.flush()

            movimiento = MovimientoCaja(

                caja_id=caja.id,

                tipo="APERTURA",

                monto=fondo,

                usuario_id=current_user.id,

                observaciones="Apertura de caja"

            )

            db.session.add(movimiento)

            registrar_auditoria(

                "CAJA",

                "APERTURA",

                f"Caja {caja.id}: saldo inicial ${fondo:.2f}"

            )

            db.session.commit()

            flash(

                "Caja abierta correctamente.",

                "success"

            )

            return redirect(

                url_for("caja")

            )

        except Exception as e:

            db.session.rollback()

            flash(

                str(e),

                "danger"

            )

    ultima = Caja.query.filter_by(
        unidad_negocio_id=current_user.unidad_negocio_id,
        abierta=False
    ).order_by(Caja.fecha_cierre.desc()).first()

    return render_template(

        "abrir_caja.html",

        ultima=ultima

    )

###############################################################
# MOVIMIENTO MANUAL DE CAJA
###############################################################

@app.route("/caja/movimiento", methods=["GET", "POST"])
@login_required
@modulo_requerido("CAJA")
def movimiento_caja():

    if not es_gerente_caja():

        flash(
            "Solo el gerente puede registrar entradas o salidas de caja.",
            "danger"
        )

        return redirect(url_for("caja"))

    caja = Caja.query.filter_by(
        unidad_negocio_id=current_user.unidad_negocio_id,
        abierta=True
    ).first()

    if not caja:

        flash(
            "No existe una caja abierta.",
            "warning"
        )

        return redirect(url_for("caja"))

    if request.method == "POST":

        try:

            tipo = request.form["tipo"]

            monto = float(request.form["monto"])

            observaciones = request.form.get(
                "observaciones",
                ""
            )

            if monto <= 0:

                raise ValueError(
                    "El monto debe ser mayor que cero."
                )

            if tipo == "ENTRADA":

                caja.saldo_actual += monto

            elif tipo == "SALIDA":

                if caja.saldo_actual < monto:

                    raise ValueError(
                        "Saldo insuficiente en caja."
                    )

                caja.saldo_actual -= monto

            else:

                raise ValueError(
                    "Tipo de movimiento inválido."
                )

            movimiento = MovimientoCaja(

                caja_id=caja.id,

                tipo=tipo,

                monto=monto,

                usuario_id=current_user.id,

                observaciones=observaciones

            )

            db.session.add(movimiento)

            registrar_auditoria(

                "CAJA",

                tipo,

                f"${monto:.2f}"

            )

            db.session.commit()

            flash(
                "Movimiento registrado correctamente.",
                "success"
            )

            return redirect(
                url_for("caja")
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    return render_template(

        "movimiento_caja.html",

        caja=caja

    )

###############################################################
# CERRAR CAJA
###############################################################

@app.route("/caja/cerrar", methods=["GET", "POST"])
@login_required
@modulo_requerido("CAJA")
def cerrar_caja():

    if not es_gerente_caja():

        flash(
            "Solo el gerente puede realizar el corte de caja.",
            "danger"
        )

        return redirect(url_for("caja"))

    caja = Caja.query.filter_by(
        unidad_negocio_id=current_user.unidad_negocio_id,
        abierta=True
    ).first()

    if not caja:

        flash(
            "No existe una caja abierta.",
            "warning"
        )

        return redirect(url_for("caja"))

    if request.method == "POST":

        try:

            efectivo_real = float(
                request.form["efectivo_real"]
            )

            if efectivo_real < 0:

                raise ValueError("El efectivo contado no puede ser negativo.")

            caja.efectivo_final = efectivo_real

            caja.diferencia = efectivo_real - caja.saldo_actual

            caja.abierta = False

            caja.fecha_cierre = datetime.now()

            movimiento = MovimientoCaja(

                caja_id=caja.id,

                tipo="CIERRE",

                monto=efectivo_real,

                usuario_id=current_user.id,

                observaciones="Cierre de caja"

            )

            db.session.add(movimiento)

            registrar_auditoria(

                "CAJA",

                "CIERRE",

                f"Caja {caja.id}: esperado ${caja.saldo_actual:.2f}, contado ${efectivo_real:.2f}, diferencia ${caja.diferencia:.2f}"

            )

            db.session.commit()

            if caja.diferencia == 0:

                flash(
                    "Caja cerrada correctamente.",
                    "success"
                )

            else:

                flash(
                    f"Caja cerrada. Diferencia: ${caja.diferencia:.2f}",
                    "warning"
                )

            return redirect(
                url_for("detalle_caja", id=caja.id)
            )

        except Exception as e:

            db.session.rollback()

            flash(
                str(e),
                "danger"
            )

    return render_template(

        "cerrar_caja.html",

        caja=caja

    )

###############################################################
# CORTE DIARIO DE CAJA
###############################################################

@app.route("/caja/corte")
@login_required
@modulo_requerido("CAJA")
def corte_caja():

    caja = (
        Caja.query
        .filter_by(
            unidad_negocio_id=current_user.unidad_negocio_id,
            abierta=False
        )
        .order_by(Caja.fecha_cierre.desc())
        .first()
    )

    if not caja:

        flash("No existen cortes de caja.", "warning")

        return redirect(url_for("caja"))

    return redirect(url_for("detalle_caja", id=caja.id))

###############################################################
# REPORTES
###############################################################

def _ambito_analisis(empresa_id=None, unidad_id=None):
    """Resuelve el alcance autorizado antes de consultar cualquier métrica."""
    if getattr(current_user, "administrador_principal", False):
        if unidad_id:
            unidad = UnidadNegocio.query.get_or_404(unidad_id)
            if empresa_id and unidad.empresa_id != empresa_id:
                abort(400)
            return [unidad.id], unidad.empresa_id, unidad.id
        if empresa_id:
            empresa = Empresa.query.get_or_404(empresa_id)
            return [u.id for u in empresa.unidades], empresa.id, None
        return [u.id for u in UnidadNegocio.query.all()], None, None

    if current_user.unidad_negocio_id is None and current_user.empresa_id:
        if not (tiene_permiso("ANALISIS_DATOS") or tiene_permiso("REPORTES")) or not current_user.empresa_id:
            abort(403)
        if empresa_id and empresa_id != current_user.empresa_id:
            abort(403)
        empresa = Empresa.query.get_or_404(current_user.empresa_id)
        if unidad_id:
            unidad = UnidadNegocio.query.get_or_404(unidad_id)
            if unidad.empresa_id != empresa.id:
                abort(403)
            return [unidad.id], empresa.id, unidad.id
        return [u.id for u in empresa.unidades], empresa.id, None

    if not (tiene_permiso("ANALISIS_DATOS") or tiene_permiso("REPORTES")) or not current_user.unidad_negocio_id:
        abort(403)
    if empresa_id and empresa_id != current_user.empresa_id:
        abort(403)
    if unidad_id and unidad_id != current_user.unidad_negocio_id:
        abort(403)
    return [current_user.unidad_negocio_id], current_user.empresa_id, current_user.unidad_negocio_id


def _metricas_analisis(unidad_ids, fecha_inicio, fecha_fin):
    if not unidad_ids:
        return {
            "ventas": 0.0, "compras": 0.0, "entradas_caja": 0.0,
            "salidas_caja": 0.0, "inventario_costo_estimado": 0.0,
            "ventas_cantidad": 0, "compras_cantidad": 0,
            "utilidad_bruta_estimada": 0.0
        }

    ventas_q = Venta.query.filter(
        Venta.unidad_negocio_id.in_(unidad_ids),
        Venta.estado == "ACTIVA",
        Venta.fecha >= fecha_inicio,
        Venta.fecha < fecha_fin
    )
    compras_q = Compra.query.filter(
        Compra.unidad_negocio_id.in_(unidad_ids),
        Compra.fecha >= fecha_inicio,
        Compra.fecha < fecha_fin
    )
    ventas = ventas_q.with_entities(
        func.coalesce(func.sum(Venta.total), 0), func.count(Venta.id)
    ).first()
    compras = compras_q.with_entities(
        func.coalesce(func.sum(Compra.total), 0), func.count(Compra.id)
    ).first()

    entradas = db.session.query(
        func.coalesce(func.sum(MovimientoCaja.monto), 0)
    ).join(Caja, MovimientoCaja.caja_id == Caja.id).filter(
        Caja.unidad_negocio_id.in_(unidad_ids),
        MovimientoCaja.tipo == "ENTRADA",
        MovimientoCaja.fecha >= fecha_inicio,
        MovimientoCaja.fecha < fecha_fin
    ).scalar() or 0
    salidas = db.session.query(
        func.coalesce(func.sum(MovimientoCaja.monto), 0)
    ).join(Caja, MovimientoCaja.caja_id == Caja.id).filter(
        Caja.unidad_negocio_id.in_(unidad_ids),
        MovimientoCaja.tipo == "SALIDA",
        MovimientoCaja.fecha >= fecha_inicio,
        MovimientoCaja.fecha < fecha_fin
    ).scalar() or 0
    inventario = db.session.query(
        func.coalesce(func.sum(Inventario.existencia * Producto.costo_promedio), 0)
    ).join(Producto, Inventario.producto_id == Producto.id).filter(
        Inventario.unidad_negocio_id.in_(unidad_ids)
    ).scalar() or 0

    total_ventas = float(ventas[0] or 0)
    total_compras = float(compras[0] or 0)
    return {
        "ventas": total_ventas,
        "compras": total_compras,
        "entradas_caja": float(entradas),
        "salidas_caja": float(salidas),
        "inventario_costo_estimado": float(inventario),
        "ventas_cantidad": int(ventas[1] or 0),
        "compras_cantidad": int(compras[1] or 0),
        "utilidad_bruta_estimada": total_ventas - total_compras,
    }


def _periodo_analisis():
    hoy = date.today()
    inicio = request.args.get("desde", f"{hoy.year}-01-01")
    fin = request.args.get("hasta", hoy.isoformat())
    try:
        desde = date.fromisoformat(inicio)
        hasta = date.fromisoformat(fin)
    except ValueError:
        abort(400, "Fechas inválidas; usa el formato AAAA-MM-DD.")
    if hasta < desde:
        abort(400, "La fecha final debe ser igual o posterior a la inicial.")
    return datetime.combine(desde, datetime.min.time()), datetime.combine(
        hasta + timedelta(days=1), datetime.min.time()
    ), desde.isoformat(), hasta.isoformat()


@app.route("/analisis-datos", methods=["GET", "POST"])
@login_required
def analisis_datos():
    unidad_ids, empresa_id, unidad_id = _ambito_analisis(
        request.args.get("empresa_id", type=int),
        request.args.get("unidad_id", type=int)
    )
    inicio, fin, desde_texto, hasta_texto = _periodo_analisis()
    metricas = _metricas_analisis(unidad_ids, inicio, fin)
    unidades_scope = UnidadNegocio.query.filter(
        UnidadNegocio.id.in_(unidad_ids)
    ).order_by(UnidadNegocio.nombre).all() if unidad_ids else []
    resumen_unidades = [
        {
            "nombre": unidad.nombre,
            **_metricas_analisis([unidad.id], inicio, fin),
        }
        for unidad in unidades_scope
    ]
    escenario = None
    valores_form = {}

    if request.method == "POST":
        try:
            valores_form = {
                "inversion": float(request.form.get("inversion", "0")),
                "ingresos_anuales": float(request.form.get("ingresos_anuales", "0")),
                "costos_anuales": float(request.form.get("costos_anuales", "0")),
                "tasa": float(request.form.get("tasa", "10")) / 100,
                "anios": int(request.form.get("anios", "5")),
                "valor_residual": float(request.form.get("valor_residual", "0")),
            }
            if not all(math.isfinite(valor) for valor in valores_form.values()):
                raise ValueError("Todos los valores deben ser números finitos.")
            if valores_form["inversion"] < 0 or valores_form["ingresos_anuales"] < 0 \
                    or valores_form["costos_anuales"] < 0 or valores_form["valor_residual"] < 0:
                raise ValueError("Los montos no pueden ser negativos.")
            if any(
                valores_form[campo] > 1e15
                for campo in ("inversion", "ingresos_anuales", "costos_anuales", "valor_residual")
            ):
                raise ValueError("Cada monto debe ser menor o igual a 1,000,000,000,000,000.")
            if not 0 <= valores_form["tasa"] <= 5:
                raise ValueError("La tasa debe estar entre 0% y 500%.")
            if not 1 <= valores_form["anios"] <= 100:
                raise ValueError("El plazo debe estar entre 1 y 100 años.")
            escenario = analizar_escenario(**valores_form)
        except (TypeError, ValueError) as e:
            flash(f"No fue posible calcular el escenario: {e}", "warning")

    empresas = Empresa.query.order_by(Empresa.nombre).all() \
        if getattr(current_user, "administrador_principal", False) else []
    unidades = UnidadNegocio.query.filter(
        UnidadNegocio.empresa_id == empresa_id
    ).order_by(UnidadNegocio.nombre).all() if empresa_id else []

    return render_template(
        "analisis_datos.html",
        metricas=metricas,
        resumen_unidades=resumen_unidades,
        escenario=escenario,
        valores_form=valores_form,
        empresas=empresas,
        unidades=unidades,
        empresa_id=empresa_id,
        unidad_id=unidad_id,
        desde=desde_texto,
        hasta=hasta_texto,
    )


@app.route("/analisis-datos/chat", methods=["POST"])
@login_required
def analisis_datos_chat():
    payload = request.get_json(silent=True) or {}
    unidad_ids, _, _ = _ambito_analisis(
        payload.get("empresa_id"), payload.get("unidad_id")
    )
    pregunta = str(payload.get("pregunta", "")).strip()
    if not pregunta or len(pregunta) > 2000:
        return {"error": "Escribe una pregunta de hasta 2,000 caracteres."}, 400

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {
            "error": "El análisis numérico está disponible. Para activar el chat configura OPENAI_API_KEY en el entorno del servidor."
        }, 503

    hoy = date.today()
    desde = payload.get("desde")
    hasta = payload.get("hasta")
    try:
        inicio = datetime.combine(date.fromisoformat(desde), datetime.min.time()) if desde else datetime(hoy.year, 1, 1)
        fin = datetime.combine(date.fromisoformat(hasta) + timedelta(days=1), datetime.min.time()) if hasta else datetime.combine(hoy + timedelta(days=1), datetime.min.time())
    except (TypeError, ValueError):
        return {"error": "El período de análisis no es válido."}, 400
    metricas = _metricas_analisis(
        unidad_ids,
        inicio,
        fin
    )
    cuerpo = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un asistente de análisis gerencial. Responde en español, "
                    "explica supuestos y limita recomendaciones a los agregados "
                    "proporcionados. Distingue ventas de cobros, compras de gastos, "
                    "y utilidad bruta estimada de utilidad neta. No inventes datos. "
                    "Aclara que no es asesoría contable o financiera profesional. "
                    "Los costos de compra registrados no necesariamente coinciden "
                    "con el costo de ventas; evita llamar utilidad neta al margen estimado."
                ),
            },
            {
                "role": "user",
                "content": f"Indicadores agregados del período {inicio.date()} a {(fin - timedelta(days=1)).date()} (MXN): "
                + json.dumps(metricas, ensure_ascii=False)
                + "\nPregunta: " + pregunta,
            },
        ],
        "temperature": 0.2,
        "max_tokens": 800,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as respuesta:
            resultado = json.loads(respuesta.read().decode("utf-8"))
        return {"respuesta": resultado["choices"][0]["message"]["content"]}
    except urllib.error.HTTPError as e:
        app.logger.warning("OpenAI request returned HTTP %s", e.code)
        return {"error": "El servicio de análisis IA no está disponible ahora."}, 502
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError):
        return {"error": "No se pudo completar el análisis IA; intenta de nuevo."}, 502

@app.route("/reportes")
@login_required
@modulo_requerido("REPORTES")
def reportes():
    empresa_param = request.args.get("empresa_id", type=int)
    unidad_param = request.args.get("unidad_id", type=int)
    unidad_ids, empresa_id, unidad_id = _ambito_analisis(
        empresa_param, unidad_param
    )
    inicio, fin, desde, hasta = _periodo_analisis()
    resumen = _metricas_analisis(unidad_ids, inicio, fin)
    comparativo = []
    if len(unidad_ids) > 1:
        unidades_scope = UnidadNegocio.query.filter(
            UnidadNegocio.id.in_(unidad_ids)
        ).order_by(UnidadNegocio.nombre).all()
        comparativo = [
            {"id": u.id, "nombre": u.nombre, **_metricas_analisis([u.id], inicio, fin)}
            for u in unidades_scope
        ]

    ventas = Venta.query.filter(
        Venta.unidad_negocio_id.in_(unidad_ids),
        Venta.estado == "ACTIVA",
        Venta.fecha >= inicio,
        Venta.fecha < fin
    ).order_by(Venta.fecha.desc()).limit(100).all() if unidad_id or getattr(
        current_user, "administrador_principal", False
    ) else []
    compras = Compra.query.filter(
        Compra.unidad_negocio_id.in_(unidad_ids),
        Compra.fecha >= inicio,
        Compra.fecha < fin
    ).order_by(Compra.fecha.desc()).limit(100).all() if unidad_id or getattr(
        current_user, "administrador_principal", False
    ) else []

    empresas = []
    if getattr(current_user, "administrador_principal", False):
        empresas = Empresa.query.order_by(Empresa.nombre).all()
    elif current_user.unidad_negocio_id is None and current_user.empresa_id:
        empresas = [Empresa.query.get_or_404(current_user.empresa_id)]
    unidades = UnidadNegocio.query.filter(
        UnidadNegocio.empresa_id == empresa_id
    ).order_by(UnidadNegocio.nombre).all() if empresa_id else []

    return render_template(
        "reportes.html",
        resumen=resumen,
        comparativo=comparativo,
        ventas=ventas,
        compras=compras,
        empresas=empresas,
        unidades=unidades,
        empresa_id=empresa_id,
        unidad_id=unidad_id,
        desde=desde,
        hasta=hasta,
    )


def _unidades_reporte_actual():
    if getattr(current_user, "administrador_principal", False):
        return [unidad.id for unidad in UnidadNegocio.query.all()]
    if current_user.unidad_negocio_id is None and current_user.empresa_id:
        return [
            unidad.id for unidad in UnidadNegocio.query.filter_by(
                empresa_id=current_user.empresa_id
            ).all()
        ]
    return [current_user.unidad_negocio_id] if current_user.unidad_negocio_id else []


def _filtros_exportacion_reporte():
    unidad_ids, _, _ = _ambito_analisis(
        request.args.get("empresa_id", type=int),
        request.args.get("unidad_id", type=int)
    )
    inicio, fin, desde, hasta = _periodo_analisis()
    return unidad_ids, inicio, fin, desde, hasta


###############################################################
# REPORTE DIARIO
###############################################################

@app.route("/reportes/diario")
@login_required
@modulo_requerido("REPORTES")
def reporte_diario():

    from sqlalchemy import func

    hoy = date.today()
    return redirect(url_for(
        "reportes", desde=hoy.isoformat(), hasta=hoy.isoformat()
    ))
    unidad_ids = _unidades_reporte_actual()

    ventas = (
        Venta.query
        .filter(
            db.func.date(Venta.fecha) == hoy,
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA"
        )
        .all()
    )

    total_ventas = sum(
        venta.total
        for venta in ventas
    )

    compras = (
        Compra.query
        .filter(
            db.func.date(Compra.fecha) == hoy,
            Compra.unidad_negocio_id.in_(unidad_ids)
        )
        .all()
    )

    total_compras = sum(
        compra.total
        for compra in compras
    )

    apartados = (
        Apartado.query
        .filter(
            db.func.date(Apartado.fecha) == hoy,
            Apartado.unidad_negocio_id.in_(unidad_ids)
        )
        .all()
    )

    return render_template(

        "reporte_diario.html",

        fecha=hoy,

        ventas=ventas,

        compras=compras,

        apartados=apartados,

        total_ventas=total_ventas,

        total_compras=total_compras

    )

###############################################################
# REPORTE MENSUAL
###############################################################

@app.route("/reportes/mensual")
@login_required
@modulo_requerido("REPORTES")
def reporte_mensual():

    from sqlalchemy import extract

    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    siguiente_mes = (inicio_mes + timedelta(days=32)).replace(day=1)
    fin_mes = siguiente_mes - timedelta(days=1)
    return redirect(url_for(
        "reportes", desde=inicio_mes.isoformat(), hasta=fin_mes.isoformat()
    ))
    unidad_ids = _unidades_reporte_actual()

    ventas = (
        Venta.query
        .filter(
            extract("year", Venta.fecha) == hoy.year,
            extract("month", Venta.fecha) == hoy.month,
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA"
        )
        .all()
    )

    compras = (
        Compra.query
        .filter(
            extract("year", Compra.fecha) == hoy.year,
            extract("month", Compra.fecha) == hoy.month,
            Compra.unidad_negocio_id.in_(unidad_ids)
        )
        .all()
    )

    apartados = (
        Apartado.query
        .filter(
            extract("year", Apartado.fecha) == hoy.year,
            extract("month", Apartado.fecha) == hoy.month,
            Apartado.unidad_negocio_id.in_(unidad_ids)
        )
        .all()
    )

    total_ventas = sum(v.total for v in ventas)
    total_compras = sum(c.total for c in compras)
    total_apartados = sum(a.total for a in apartados)

    utilidad = total_ventas - total_compras

    return render_template(

        "reporte_mensual.html",

        ventas=ventas,

        compras=compras,

        apartados=apartados,

        total_ventas=total_ventas,

        total_compras=total_compras,

        total_apartados=total_apartados,

        utilidad=utilidad,

        anio=hoy.year,

        mes=hoy.month

    )

###############################################################
# REPORTE TRIMESTRAL
###############################################################

@app.route("/reportes/trimestral")
@login_required
@modulo_requerido("REPORTES")
def reporte_trimestral():

    hoy = date.today()

    trimestre = ((hoy.month - 1) // 3) + 1

    mes_inicio = (trimestre - 1) * 3 + 1

    mes_fin = mes_inicio + 2
    inicio_trimestre = date(hoy.year, mes_inicio, 1)
    siguiente_trimestre = date(hoy.year, mes_fin, 1) + timedelta(days=32)
    siguiente_trimestre = siguiente_trimestre.replace(day=1)
    fin_trimestre = siguiente_trimestre - timedelta(days=1)
    return redirect(url_for(
        "reportes", desde=inicio_trimestre.isoformat(), hasta=fin_trimestre.isoformat()
    ))
    unidad_ids = _unidades_reporte_actual()

    ventas = (
        Venta.query
        .filter(
            extract("year", Venta.fecha) == hoy.year,
            extract("month", Venta.fecha) >= mes_inicio,
            extract("month", Venta.fecha) <= mes_fin,
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA"
        )
        .all()
    )

    compras = (
        Compra.query
        .filter(
            extract("year", Compra.fecha) == hoy.year,
            extract("month", Compra.fecha) >= mes_inicio,
            extract("month", Compra.fecha) <= mes_fin,
            Compra.unidad_negocio_id.in_(unidad_ids)
        )
        .all()
    )

    total_ventas = sum(v.total for v in ventas)
    total_compras = sum(c.total for c in compras)

    return render_template(

        "reporte_trimestral.html",

        ventas=ventas,

        compras=compras,

        total_ventas=total_ventas,

        total_compras=total_compras,

        utilidad=total_ventas-total_compras,

        trimestre=trimestre,

        anio=hoy.year

    )


###############################################################
# REPORTE SEMESTRAL
###############################################################

@app.route("/reportes/semestral")
@login_required
@modulo_requerido("REPORTES")
def reporte_semestral():

    hoy = date.today()

    semestre = 1 if hoy.month <= 6 else 2

    inicio = 1 if semestre == 1 else 7

    fin = 6 if semestre == 1 else 12
    inicio_semestre = date(hoy.year, inicio, 1)
    fin_semestre = date(hoy.year, fin, 31 if fin in (1, 3, 5, 7, 8, 10, 12) else 30)
    return redirect(url_for(
        "reportes", desde=inicio_semestre.isoformat(), hasta=fin_semestre.isoformat()
    ))
    unidad_ids = _unidades_reporte_actual()

    ventas = (
        Venta.query
        .filter(
            extract("year", Venta.fecha) == hoy.year,
            extract("month", Venta.fecha) >= inicio,
            extract("month", Venta.fecha) <= fin,
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA"
        )
        .all()
    )

    compras = (
        Compra.query
        .filter(
            extract("year", Compra.fecha) == hoy.year,
            extract("month", Compra.fecha) >= inicio,
            extract("month", Compra.fecha) <= fin,
            Compra.unidad_negocio_id.in_(unidad_ids)
        )
        .all()
    )

    total_ventas = sum(v.total for v in ventas)

    total_compras = sum(c.total for c in compras)

    return render_template(

        "reporte_semestral.html",

        ventas=ventas,

        compras=compras,

        total_ventas=total_ventas,

        total_compras=total_compras,

        utilidad=total_ventas-total_compras,

        semestre=semestre,

        anio=hoy.year

    )


###############################################################
# REPORTE ANUAL
###############################################################

@app.route("/reportes/anual")
@login_required
@modulo_requerido("REPORTES")
def reporte_anual():

    hoy = date.today()
    return redirect(url_for(
        "reportes",
        desde=date(hoy.year, 1, 1).isoformat(),
        hasta=date(hoy.year, 12, 31).isoformat()
    ))
    unidad_ids = _unidades_reporte_actual()

    ventas = (
        Venta.query
        .filter(
            extract("year", Venta.fecha) == hoy.year,
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA"
        )
        .all()
    )

    compras = (
        Compra.query
        .filter(
            extract("year", Compra.fecha) == hoy.year,
            Compra.unidad_negocio_id.in_(unidad_ids)
        )
        .all()
    )

    apartados = (
        Apartado.query
        .filter(
            extract("year", Apartado.fecha) == hoy.year,
            Apartado.unidad_negocio_id.in_(unidad_ids)
        )
        .all()
    )

    total_ventas = sum(v.total for v in ventas)

    total_compras = sum(c.total for c in compras)

    total_apartados = sum(a.total for a in apartados)

    utilidad = total_ventas - total_compras

    return render_template(

        "reporte_anual.html",

        ventas=ventas,

        compras=compras,

        apartados=apartados,

        total_ventas=total_ventas,

        total_compras=total_compras,

        total_apartados=total_apartados,

        utilidad=utilidad,

        anio=hoy.year

    )

###############################################################
# DASHBOARD EJECUTIVO
###############################################################

@app.route("/dashboard/ejecutivo")
@login_required
@modulo_requerido("REPORTES")
def dashboard_ejecutivo():

    from sqlalchemy import func

    hoy = date.today()
    inicio_mes_actual = hoy.replace(day=1)
    return redirect(url_for(
        "reportes", desde=inicio_mes_actual.isoformat(), hasta=hoy.isoformat()
    ))
    unidad_ids = _unidades_reporte_actual()

    ############################################################
    # VENTAS DEL DÍA
    ############################################################

    ventas_hoy = (
        db.session.query(
            func.sum(Venta.total)
        )
        .filter(
            db.func.date(Venta.fecha) == hoy,
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA"
        )
        .scalar()
    ) or 0

    ############################################################
    # VENTAS DEL MES
    ############################################################

    ventas_mes = (
        db.session.query(
            func.sum(Venta.total)
        )
        .filter(
            extract("year", Venta.fecha) == hoy.year,
            extract("month", Venta.fecha) == hoy.month,
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA"
        )
        .scalar()
    ) or 0

    ############################################################
    # COMPRAS DEL MES
    ############################################################

    compras_mes = (
        db.session.query(
            func.sum(Compra.total)
        )
        .filter(
            extract("year", Compra.fecha) == hoy.year,
            extract("month", Compra.fecha) == hoy.month,
            Compra.unidad_negocio_id.in_(unidad_ids)
        )
        .scalar()
    ) or 0

    ############################################################
    # APARTADOS ACTIVOS
    ############################################################

    apartados_activos = Apartado.query.filter(
        Apartado.unidad_negocio_id.in_(unidad_ids),
        Apartado.estado == "ACTIVO"
    ).count()

    ############################################################
    # CLIENTES
    ############################################################

    clientes = Cliente.query.filter(
        Cliente.unidad_negocio_id.in_(unidad_ids),
        Cliente.activo.is_(True)
    ).count()

    ############################################################
    # PRODUCTOS
    ############################################################

    productos = Producto.query.filter(
        Producto.unidad_negocio_id.in_(unidad_ids),
        Producto.activo.is_(True)
    ).count()

    ############################################################
    # UTILIDAD ESTIMADA
    ############################################################

    utilidad = ventas_mes - compras_mes

    ############################################################
    # ALERTAS DEL DASHBOARD
    ############################################################

    alertas = []
    for unidad_scope_id in unidad_ids:
        alertas.extend(obtener_alertas_dashboard(unidad_scope_id))

    total_alertas = len(alertas)

    return render_template(

    "dashboard_ejecutivo.html",

    ventas_hoy=ventas_hoy,

    ventas_mes=ventas_mes,

    compras_mes=compras_mes,

    utilidad=utilidad,

    clientes=clientes,

    productos=productos,

    apartados=apartados_activos,

    alertas=alertas,

    total_alertas=total_alertas

    )

###############################################################
# EXPORTAR REPORTE A EXCEL
###############################################################

from openpyxl import Workbook
from flask import send_file
import io


@app.route("/reportes/exportar/excel")
@login_required
@modulo_requerido("REPORTES")
def exportar_reporte_excel():

    unidad_ids, inicio, fin, desde, hasta = _filtros_exportacion_reporte()

    wb = Workbook()

    ws = wb.active

    ws.title = "Ventas"

    ws.append([
        "Fecha",
        "Folio",
        "Unidad",
        "Cliente",
        "Total",
        "Método de Pago",
        "Estado"
    ])

    ventas = (
        Venta.query
        .filter(
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA",
            Venta.fecha >= inicio,
            Venta.fecha < fin
        )
        .order_by(
            Venta.fecha.desc()
        )
        .all()
    )

    for venta in ventas:

        cliente = ""

        if venta.cliente:
            cliente = venta.cliente.nombre

        ws.append([

            venta.fecha.strftime("%d/%m/%Y %H:%M"),

            venta.numero_venta,

            venta.unidad.nombre if venta.unidad else "",

            cliente,

            float(venta.total),

            venta.metodo_pago,

            venta.estado

        ])

    ws_compras = wb.create_sheet("Compras")
    ws_compras.append(["Fecha", "Folio", "Unidad", "Proveedor", "Total"])
    compras_exportadas = Compra.query.filter(
        Compra.unidad_negocio_id.in_(unidad_ids),
        Compra.fecha >= inicio,
        Compra.fecha < fin
    ).order_by(Compra.fecha.desc()).all() if unidad_ids else []
    for compra in compras_exportadas:
        ws_compras.append([
            compra.fecha.strftime("%d/%m/%Y %H:%M"),
            compra.numero_compra,
            compra.unidad.nombre if compra.unidad else "",
            compra.proveedor.nombre if compra.proveedor else "",
            float(compra.total or 0),
        ])

    archivo = io.BytesIO()

    wb.save(archivo)

    archivo.seek(0)

    return send_file(

        archivo,

        download_name=f"Reporte_Ventas_{desde}_{hasta}.xlsx",

        as_attachment=True,

        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    )

###############################################################
# EXPORTAR REPORTE A PDF
###############################################################

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph
)
from reportlab.lib.styles import getSampleStyleSheet


@app.route("/reportes/exportar/pdf")
@login_required
@modulo_requerido("REPORTES")
def exportar_reporte_pdf():

    unidad_ids, inicio, fin, desde, hasta = _filtros_exportacion_reporte()

    ventas = (
        Venta.query
        .filter(
            Venta.unidad_negocio_id.in_(unidad_ids),
            Venta.estado == "ACTIVA",
            Venta.fecha >= inicio,
            Venta.fecha < fin
        )
        .order_by(
            Venta.fecha.desc()
        )
        .limit(500)
        .all()
    )

    buffer = io.BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter)
    )

    estilos = getSampleStyleSheet()

    elementos = []

    elementos.append(
        Paragraph(
            f"REPORTE DE VENTAS {desde} - {hasta}",
            estilos["Heading1"]
        )
    )

    datos = [[
        "Fecha",
        "Folio",
        "Unidad",
        "Cliente",
        "Total",
        "Pago",
        "Estado"
    ]]

    for venta in ventas:

        cliente = ""

        if venta.cliente:
            cliente = venta.cliente.nombre

        datos.append([

            venta.fecha.strftime("%d/%m/%Y"),

            venta.numero_venta,

            venta.unidad.nombre if venta.unidad else "",

            cliente,

            f"${venta.total:,.2f}",

            venta.metodo_pago,

            venta.estado

        ])

    tabla = Table(datos)

    tabla.setStyle(

        TableStyle([

            ("BACKGROUND", (0,0), (-1,0), colors.darkblue),

            ("TEXTCOLOR", (0,0), (-1,0), colors.white),

            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),

            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),

            ("ALIGN", (0,0), (-1,-1), "CENTER"),

            ("BOTTOMPADDING", (0,0), (-1,0), 10)

        ])

    )

    elementos.append(tabla)
    ventas_total = Venta.query.filter(
        Venta.unidad_negocio_id.in_(unidad_ids),
        Venta.estado == "ACTIVA",
        Venta.fecha >= inicio,
        Venta.fecha < fin
    ) if unidad_ids else Venta.query.filter(Venta.id == -1)
    if ventas_total.count() > 500:
        elementos.append(Paragraph("El PDF limita las ventas a 500 registros; Excel incluye el período completo.", estilos["Italic"]))

    compras_total = Compra.query.filter(
        Compra.unidad_negocio_id.in_(unidad_ids),
        Compra.fecha >= inicio,
        Compra.fecha < fin
    ) if unidad_ids else Compra.query.filter(Compra.id == -1)
    compras_pdf = compras_total.order_by(Compra.fecha.desc()).limit(500).all()

    elementos.append(Paragraph("COMPRAS REGISTRADAS", estilos["Heading2"]))
    datos_compras = [["Fecha", "Folio", "Unidad", "Proveedor", "Total"]]
    for compra in compras_pdf:
        datos_compras.append([
            compra.fecha.strftime("%d/%m/%Y"),
            compra.numero_compra,
            compra.unidad.nombre if compra.unidad else "",
            compra.proveedor.nombre if compra.proveedor else "",
            f"${(compra.total or 0):,.2f}",
        ])
    compras_tabla = Table(datos_compras, repeatRows=1)
    compras_tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.darkgreen),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    elementos.append(compras_tabla)
    if compras_total.count() > 500:
        elementos.append(Paragraph("El PDF limita la lista de compras a 500 documentos; Excel incluye el período completo.", estilos["Italic"]))

    documento.build(elementos)

    buffer.seek(0)

    return send_file(

        buffer,

        download_name=f"Reporte_Ventas_{desde}_{hasta}.pdf",

        as_attachment=True,

        mimetype="application/pdf"

    )

###############################################################
# ALERTAS DEL SISTEMA
###############################################################

@app.route("/alertas")
@login_required
def alertas():

    alertas = []

    ############################################################
    # STOCK MÍNIMO
    ############################################################

    inventarios = Inventario.query.filter_by(
        unidad_negocio_id=current_user.unidad_negocio_id
    ).all()

    for inv in inventarios:

        if inv.existencia <= inv.stock_minimo:

            alertas.append({

                "tipo": "STOCK",

                "color": "danger",

                "titulo": "Stock mínimo",

                "mensaje": (
                    f"{inv.producto.nombre} "
                    f"tiene únicamente {inv.existencia} piezas."
                )

            })

    ############################################################
    # APARTADOS POR VENCER
    ############################################################

    limite = datetime.now().date() + timedelta(days=3)

    apartados = Apartado.query.filter(

        Apartado.unidad_negocio_id == current_user.unidad_negocio_id,

        Apartado.estado == "ACTIVO",

        Apartado.fecha_limite <= limite

    ).all()

    for apartado in apartados:

        alertas.append({

            "tipo": "APARTADO",

            "color": "warning",

            "titulo": "Apartado próximo a vencer",

            "mensaje": (
                f"{apartado.numero_apartado} - "
                f"{apartado.cliente.nombre}"
            )

        })

    ############################################################
    # CRÉDITOS VENCIDOS
    ############################################################

    creditos = CreditoCliente.query.join(
        Cliente, Cliente.id == CreditoCliente.cliente_id
    ).filter(

        Cliente.unidad_negocio_id == current_user.unidad_negocio_id,

        CreditoCliente.saldo > 0

    ).all()

    for credito in creditos:

        alertas.append({

            "tipo": "CREDITO",

            "color": "info",

            "titulo": "Crédito pendiente",

            "mensaje": (
                f"{credito.cliente.nombre} "
                f"adeuda ${credito.saldo:,.2f}"
            )

        })

    ############################################################
    # CAJA ABIERTA
    ############################################################

    caja = Caja.query.filter_by(

        unidad_negocio_id=current_user.unidad_negocio_id,

        abierta=True

    ).first()

    if caja:

        alertas.append({

            "tipo": "CAJA",

            "color": "secondary",

            "titulo": "Caja abierta",

            "mensaje": (
                "Existe una caja pendiente de cierre."
            )

        })

    return render_template(

        "alertas.html",

        alertas=alertas

    )

###############################################################
# CONTADOR DE ALERTAS
###############################################################

def obtener_alertas_dashboard(unidad_negocio_id):

    alertas = []

    ############################################################
    # STOCK MÍNIMO
    ############################################################

    inventarios = Inventario.query.filter_by(
        unidad_negocio_id=unidad_negocio_id
    ).all()

    for inv in inventarios:

        if inv.existencia <= inv.stock_minimo:

            alertas.append({

                "tipo": "STOCK",

                "prioridad": 1,

                "icono": "bi-exclamation-triangle-fill",

                "titulo": "Stock mínimo",

                "mensaje": (
                    f"{inv.producto.nombre} "
                    f"({inv.existencia})"
                )

            })

    ############################################################
    # APARTADOS
    ############################################################

    fecha_limite = datetime.now().date() + timedelta(days=3)

    apartados = Apartado.query.filter(

        Apartado.unidad_negocio_id == unidad_negocio_id,

        Apartado.estado == "ACTIVO",

        Apartado.fecha_limite <= fecha_limite

    ).count()

    if apartados:

        alertas.append({

            "tipo": "APARTADOS",

            "prioridad": 2,

            "icono": "bi-calendar-event",

            "titulo": "Apartados próximos",

            "mensaje": (
                f"{apartados} apartados por vencer"
            )

        })

    ############################################################
    # CRÉDITOS
    ############################################################

    creditos = CreditoCliente.query.join(
        Cliente, Cliente.id == CreditoCliente.cliente_id
    ).filter(

        Cliente.unidad_negocio_id == unidad_negocio_id,

        CreditoCliente.saldo > 0

    ).count()

    if creditos:

        alertas.append({

            "tipo": "CREDITOS",

            "prioridad": 2,

            "icono": "bi-cash-stack",

            "titulo": "Créditos pendientes",

            "mensaje": (
                f"{creditos} clientes"
            )

        })

    ############################################################
    # CAJA
    ############################################################

    caja = Caja.query.filter_by(

        unidad_negocio_id=unidad_negocio_id,

        abierta=True

    ).first()

    if caja:

        alertas.append({

            "tipo": "CAJA",

            "prioridad": 3,

            "icono": "bi-safe2",

            "titulo": "Caja abierta",

            "mensaje": "Pendiente de cierre"

        })

    ############################################################
    # ORDENAR POR PRIORIDAD
    ############################################################

    alertas.sort(
        key=lambda x: x["prioridad"]
    )

    return alertas

###############################################################
# RESPALDO DE BASE DE DATOS
###############################################################

import os
import shutil
from datetime import datetime, timedelta

@app.route("/sistema/respaldo")
@login_required
def respaldo_bd():
    return redirect(url_for("configuracion_sistema"))


@app.route("/seguridad")
@login_required
@modulo_requerido("SEGURIDAD")
def seguridad():
    return redirect(url_for("usuarios"))

@app.route("/configuracion")
@login_required
@modulo_requerido("CONFIGURACION")
def configuracion():
    if current_user.administrador_principal:
        return redirect(url_for("configuracion_sistema"))
    unidad_id = current_user.unidad_negocio_id
    if not unidad_id:
        abort(403)
    config = Configuracion.query.filter_by(
        unidad_negocio_id=unidad_id
    ).first()
    if not config:
        config = Configuracion(unidad_negocio_id=unidad_id)
        db.session.add(config)
        db.session.commit()
    return render_template("configuracion.html", config=config)


_ENDPOINTS_CAJA = {"caja", "abrir_caja", "movimiento_caja", "cerrar_caja", "corte_caja", "nueva_venta"}


@app.before_request
def exigir_unidad_en_caja():
    if (
        request.endpoint in _ENDPOINTS_CAJA
        and current_user.is_authenticated
        and not current_user.unidad_negocio_id
    ):
        flash(
            "Esta operación se realiza dentro de una sucursal. Entra a una sucursal para usarla.",
            "warning"
        )
        if request.endpoint == "nueva_venta":
            return redirect(url_for("dashboard"))
        return redirect(url_for("caja_historial"))


modulos_giro.registrar(
    app, db, _giro,
    SimpleNamespace(
        modulo_requerido=modulo_requerido,
        UnidadNegocio=UnidadNegocio,
        Caja=Caja,
        MovimientoCaja=MovimientoCaja,
        Proveedor=Proveedor,
        Producto=Producto,
        Cliente=Cliente,
        registrar_auditoria=registrar_auditoria,
        tiene_permiso=tiene_permiso,
        stock_producto=stock_producto,
        mover_inventario=mover_inventario,
        modulos_habilitados_empresa=lambda empresa: modulos_habilitados_empresa(empresa),
    ),
)


sistema.registrar(
    app, db, _sis,
    SimpleNamespace(
        Empresa=Empresa,
        UnidadNegocio=UnidadNegocio,
        Usuario=Usuario,
        registrar_auditoria=registrar_auditoria,
        inicializar=lambda: inicializar_sistema(
            db=db,
            Empresa=Empresa,
            UnidadNegocio=UnidadNegocio,
            Usuario=Usuario,
            Configuracion=Configuracion,
        ),
    ),
)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        migrar_admin_inicial()

        try:
            app.crear_respaldo("inicio")
        except Exception as error:
            app.logger.warning("Respaldo de inicio omitido: %s", error)

    app.iniciar_respaldo_automatico()

    puerto = int(os.environ.get("SMUNE_PORT", "5000"))
    host = os.environ.get("SMUNE_HOST", "0.0.0.0")
    print("=" * 50)
    print(f"SMUNE v1.0 - http://127.0.0.1:{puerto}")
    print("=" * 50)
    if os.environ.get("SMUNE_DEBUG") == "1":
        app.run(debug=True, host=host, port=puerto)
    else:
        from waitress import serve

        serve(app, host=host, port=puerto, threads=8)
