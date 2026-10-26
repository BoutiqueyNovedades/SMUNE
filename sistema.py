"""Respaldos, restauración, reparación de estructura y control de acceso (horarios/pausa)."""

import json
import os
import re
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from types import SimpleNamespace

from flask import (
    abort, flash, redirect, render_template, request,
    send_from_directory, url_for,
)
from flask_login import current_user, login_required, logout_user

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MAX_AUTOMATICOS = 15
_NOMBRE_VALIDO = re.compile(r"^SMUNE_\d{8}_\d{6}_[a-z_]+\.(zip|db)$")


def crear_modelos(db):
    class AjusteSistema(db.Model):
        __tablename__ = "ajuste_sistema"
        clave = db.Column(db.String(80), primary_key=True)
        valor = db.Column(db.Text)

    return SimpleNamespace(AjusteSistema=AjusteSistema)


def registrar(app, db, M, D):
    Ajuste = M.AjusteSistema
    estado_login = {}

    # ------------------------------------------------------------------ ajustes
    def leer(clave, defecto=None):
        fila = db.session.get(Ajuste, clave)
        return json.loads(fila.valor) if fila and fila.valor else defecto

    def guardar(clave, valor):
        fila = db.session.get(Ajuste, clave)
        if not fila:
            fila = Ajuste(clave=clave)
            db.session.add(fila)
        fila.valor = json.dumps(valor)

    def horario_defecto():
        return {"activo": False, "inicio": "08:00", "fin": "21:00", "dias": [0, 1, 2, 3, 4, 5]}

    def horario_de(clave):
        base = horario_defecto()
        base.update(leer(clave, {}) or {})
        return base

    def dentro_de_horario(h, ahora):
        if ahora.weekday() not in h["dias"]:
            return False
        actual = ahora.strftime("%H:%M")
        if h["inicio"] <= h["fin"]:
            return h["inicio"] <= actual <= h["fin"]
        return actual >= h["inicio"] or actual <= h["fin"]

    def motivo_bloqueo(usuario, ahora=None):
        """Devuelve el texto del bloqueo o None si el usuario puede operar."""
        if getattr(usuario, "administrador_principal", False):
            return None
        ahora = ahora or datetime.now()
        if leer("acceso_pausado", False):
            return leer("mensaje_pausa") or "El sistema está en pausa por el administrador."
        unidad_id = getattr(usuario, "unidad_negocio_id", None)
        if usuario.empresa_id and leer(f"cerrado_empresa_{usuario.empresa_id}", False):
            return "El acceso de tu empresa está cerrado. La jornada ha terminado."
        if unidad_id and leer(f"cerrado_unidad_{unidad_id}", False):
            return "El acceso de tu sucursal está cerrado. La jornada ha terminado."
        h = horario_de("horario_global")
        if usuario.empresa_id:
            propio = horario_de(f"horario_empresa_{usuario.empresa_id}")
            if propio["activo"]:
                h = propio
        if h["activo"] and not dentro_de_horario(h, ahora):
            return (
                f"Fuera del horario laboral ({h['inicio']} a {h['fin']}). "
                "Intenta de nuevo en tu horario de trabajo."
            )
        return None

    @app.before_request
    def controlar_acceso():
        if not current_user.is_authenticated:
            return None
        if request.endpoint in (None, "login", "logout", "static"):
            return None
        mensaje = motivo_bloqueo(current_user)
        if mensaje:
            logout_user()
            flash(mensaje, "warning")
            return redirect(url_for("login"))
        return None

    app.motivo_bloqueo = motivo_bloqueo

    @app.context_processor
    def estado_acceso():
        return {"acceso_pausado": bool(leer("acceso_pausado", False))}

    # ---------------------------------------------------- límite de intentos de login
    def clave_login():
        return (request.remote_addr, (request.form.get("usuario") or "").strip().lower())

    def login_bloqueado():
        dato = estado_login.get(clave_login())
        return bool(dato and dato["hasta"] > time.time())

    def login_fallo():
        clave = clave_login()
        dato = estado_login.setdefault(clave, {"n": 0, "hasta": 0})
        dato["n"] += 1
        if dato["n"] >= 5:
            dato.update(n=0, hasta=time.time() + 600)

    def login_ok():
        estado_login.pop(clave_login(), None)

    app.login_bloqueado, app.login_fallo, app.login_ok = login_bloqueado, login_fallo, login_ok

    # ------------------------------------------------------------------ respaldos
    def carpeta_respaldos():
        carpeta = app.config.get("RESPALDOS_DIR") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "respaldos"
        )
        os.makedirs(carpeta, exist_ok=True)
        return carpeta

    def ruta_bd():
        if db.engine.url.get_backend_name() != "sqlite" or not db.engine.url.database:
            raise ValueError("Los respaldos integrados solo funcionan con SQLite.")
        return db.engine.url.database

    def crear_respaldo(motivo="manual"):
        motivo = re.sub(r"[^a-z_]", "", motivo.lower()) or "manual"
        nombre = f"SMUNE_{datetime.now():%Y%m%d_%H%M%S}_{motivo}.zip"
        destino = os.path.join(carpeta_respaldos(), nombre)
        with tempfile.TemporaryDirectory() as tmp:
            copia = os.path.join(tmp, "smune.db")
            origen = sqlite3.connect(ruta_bd())
            salida = sqlite3.connect(copia)
            try:
                origen.backup(salida)
            finally:
                salida.close()
                origen.close()
            with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(copia, "smune.db")
                base = app.config["UPLOAD_FOLDER"]
                for raiz, _, archivos in os.walk(base):
                    for archivo in archivos:
                        completo = os.path.join(raiz, archivo)
                        z.write(completo, "uploads/" + os.path.relpath(completo, base).replace("\\", "/"))
        return nombre

    def listar_respaldos():
        lista = []
        for nombre in os.listdir(carpeta_respaldos()):
            if _NOMBRE_VALIDO.match(nombre):
                ruta = os.path.join(carpeta_respaldos(), nombre)
                lista.append({
                    "nombre": nombre,
                    "fecha": datetime.fromtimestamp(os.path.getmtime(ruta)),
                    "mb": os.path.getsize(ruta) / 1048576,
                    "motivo": nombre.rsplit("_", 1)[-1].split(".")[0] if nombre.count("_") >= 3 else "manual",
                })
        return sorted(lista, key=lambda r: r["fecha"], reverse=True)

    def podar_automaticos():
        autos = [r for r in listar_respaldos() if r["motivo"] in ("auto", "inicio", "cierre")]
        for viejo in autos[MAX_AUTOMATICOS:]:
            os.remove(os.path.join(carpeta_respaldos(), viejo["nombre"]))

    def reparar_estructura():
        """Crea tablas/columnas faltantes y catálogos base sin borrar datos."""
        db.create_all()
        agregadas = []
        with db.engine.begin() as conexion:
            for tabla in db.metadata.sorted_tables:
                existentes = {
                    f[1] for f in conexion.exec_driver_sql(f"PRAGMA table_info('{tabla.name}')").fetchall()
                }
                for columna in tabla.columns:
                    if columna.name not in existentes and not columna.primary_key:
                        tipo = columna.type.compile(db.engine.dialect)
                        conexion.exec_driver_sql(
                            f'ALTER TABLE "{tabla.name}" ADD COLUMN "{columna.name}" {tipo}'
                        )
                        agregadas.append(f"{tabla.name}.{columna.name}")
        D.inicializar()
        return agregadas

    def _extraer(origen_zip_o_db, tmp):
        """Devuelve la ruta de la base dentro de un respaldo y copia sus archivos subidos."""
        if zipfile.is_zipfile(origen_zip_o_db):
            with zipfile.ZipFile(origen_zip_o_db) as z:
                nombres = z.namelist()
                if "smune.db" not in nombres:
                    raise ValueError("El respaldo no contiene la base de datos.")
                z.extract("smune.db", tmp)
                base = os.path.abspath(app.config["UPLOAD_FOLDER"])
                for nombre in nombres:
                    if nombre.startswith("uploads/") and not nombre.endswith("/"):
                        destino = os.path.abspath(os.path.join(base, nombre[len("uploads/"):]))
                        if destino.startswith(base + os.sep):
                            os.makedirs(os.path.dirname(destino), exist_ok=True)
                            with z.open(nombre) as f, open(destino, "wb") as out:
                                shutil.copyfileobj(f, out)
            return os.path.join(tmp, "smune.db")
        return origen_zip_o_db

    def restaurar(origen):
        with tempfile.TemporaryDirectory() as tmp:
            candidato = _extraer(origen, tmp)
            prueba = sqlite3.connect(candidato)
            try:
                if prueba.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("El respaldo está dañado.")
                tablas = {f[0] for f in prueba.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "usuario" not in tablas:
                    raise ValueError("El archivo no es un respaldo de SMUNE.")
                crear_respaldo("pre_restauracion")
                db.session.remove()
                db.engine.dispose()
                destino = sqlite3.connect(ruta_bd())
                try:
                    prueba.backup(destino)
                finally:
                    destino.close()
            finally:
                prueba.close()
        db.engine.dispose()
        return reparar_estructura()

    app.crear_respaldo, app.reparar_estructura = crear_respaldo, reparar_estructura

    def iniciar_respaldo_automatico(horas=24):
        def ciclo():
            while True:
                try:
                    with app.app_context():
                        autos = [r for r in listar_respaldos() if r["motivo"] in ("auto", "inicio")]
                        if not autos or datetime.now() - autos[0]["fecha"] > timedelta(hours=horas):
                            crear_respaldo("auto")
                            podar_automaticos()
                except Exception as error:
                    app.logger.warning("Respaldo automático omitido: %s", error)
                time.sleep(3600)
        hilo = threading.Thread(target=ciclo, daemon=True)
        hilo.start()

    app.iniciar_respaldo_automatico = iniciar_respaldo_automatico

    # ---------------------------------------------------------------------- rutas
    def solo_principal():
        if not getattr(current_user, "administrador_principal", False):
            abort(403)

    def direcciones_red():
        try:
            ips = socket.gethostbyname_ex(socket.gethostname())[2]
        except OSError:
            ips = []
        return [ip for ip in ips if not ip.startswith("127.")]

    @app.route("/configuracion/sistema")
    @login_required
    def configuracion_sistema():
        solo_principal()
        empresas = D.Empresa.query.order_by(D.Empresa.nombre).all()
        arbol = []
        for e in empresas:
            unidades = D.UnidadNegocio.query.filter_by(empresa_id=e.id).order_by(D.UnidadNegocio.nombre).all()
            arbol.append({
                "empresa": e,
                "cerrada": leer(f"cerrado_empresa_{e.id}", False),
                "unidades": [
                    {
                        "unidad": u,
                        "cerrada": leer(f"cerrado_unidad_{u.id}", False),
                        "usuarios": D.Usuario.query.filter_by(unidad_negocio_id=u.id)
                        .order_by(D.Usuario.usuario).all(),
                    }
                    for u in unidades
                ],
            })
        return render_template(
            "configuracion_sistema.html",
            arbol=arbol,
            dias=DIAS,
            pausado=leer("acceso_pausado", False),
            mensaje_pausa=leer("mensaje_pausa", ""),
            global_h=horario_de("horario_global"),
            empresas=[(e, horario_de(f"horario_empresa_{e.id}")) for e in D.Empresa.query.order_by(D.Empresa.nombre).all()],
            respaldos=listar_respaldos(),
            ips=direcciones_red(),
            puerto=os.environ.get("SMUNE_PORT", "5000"),
            ahora=datetime.now(),
            total_usuarios=D.Usuario.query.count(),
        )

    @app.route("/configuracion/acceso/alternar", methods=["POST"])
    @login_required
    def acceso_alternar():
        solo_principal()
        pausar = not leer("acceso_pausado", False)
        if pausar:
            guardar("mensaje_pausa", leer("mensaje_pausa") or "La jornada está cerrada. Intenta más tarde.")
            try:
                crear_respaldo("cierre")
                podar_automaticos()
            except Exception as error:
                app.logger.warning("Respaldo de cierre omitido: %s", error)
        guardar("acceso_pausado", pausar)
        D.registrar_auditoria("SISTEMA", "ACCESO", "cerrado" if pausar else "abierto")
        db.session.commit()
        flash(
            "Acceso CERRADO: solo tú puedes entrar. Se guardó un respaldo."
            if pausar else "Acceso ABIERTO: los usuarios ya pueden iniciar sesión.",
            "warning" if pausar else "success",
        )
        return redirect(request.referrer or url_for("dashboard"))

    @app.route("/configuracion/acceso/<tipo>/<int:objeto_id>", methods=["POST"])
    @login_required
    def acceso_alcance(tipo, objeto_id):
        """Abre o cierra el acceso de una empresa, una sucursal o un usuario."""
        solo_principal()
        if tipo == "empresa":
            objeto = D.Empresa.query.get_or_404(objeto_id)
            clave, nombre = f"cerrado_empresa_{objeto_id}", objeto.nombre
        elif tipo == "unidad":
            objeto = D.UnidadNegocio.query.get_or_404(objeto_id)
            clave, nombre = f"cerrado_unidad_{objeto_id}", objeto.nombre
        elif tipo == "usuario":
            objeto = D.Usuario.query.get_or_404(objeto_id)
            if objeto.administrador_principal:
                abort(400)
            objeto.activo = not objeto.activo
            D.registrar_auditoria(
                "SISTEMA", "ACCESO", f"usuario {objeto.usuario} {'activado' if objeto.activo else 'desactivado'}")
            db.session.commit()
            flash(f"Usuario {objeto.usuario}: {'activo' if objeto.activo else 'desactivado'}.", "success")
            return redirect(url_for("configuracion_sistema"))
        else:
            abort(404)
        cerrar = not leer(clave, False)
        guardar(clave, cerrar)
        D.registrar_auditoria("SISTEMA", "ACCESO", f"{tipo} {nombre} {'cerrado' if cerrar else 'abierto'}")
        db.session.commit()
        flash(f"Acceso de {nombre}: {'CERRADO' if cerrar else 'ABIERTO'}.", "warning" if cerrar else "success")
        return redirect(url_for("configuracion_sistema"))

    @app.route("/configuracion/acceso", methods=["POST"])
    @login_required
    def configuracion_acceso():
        solo_principal()
        ambito = request.form.get("ambito", "global")

        def horario_form():
            inicio, fin = request.form.get("inicio", "08:00"), request.form.get("fin", "21:00")
            for valor in (inicio, fin):
                if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", valor):
                    raise ValueError("Hora inválida.")
            dias = sorted({int(d) for d in request.form.getlist("dias") if d.isdigit() and int(d) < 7})
            return {"activo": bool(request.form.get("activo")), "inicio": inicio, "fin": fin, "dias": dias}

        try:
            if ambito == "pausa":
                guardar("acceso_pausado", bool(request.form.get("pausado")))
                guardar("mensaje_pausa", (request.form.get("mensaje") or "")[:200])
                detalle = "pausa " + ("activada" if request.form.get("pausado") else "desactivada")
            elif ambito == "global":
                guardar("horario_global", horario_form())
                detalle = "horario global"
            else:
                empresa = D.Empresa.query.get_or_404(int(ambito))
                guardar(f"horario_empresa_{empresa.id}", horario_form())
                detalle = f"horario {empresa.nombre}"
            D.registrar_auditoria("SISTEMA", "ACCESO", detalle)
            db.session.commit()
            flash("Control de acceso actualizado.", "success")
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error), "danger")
        return redirect(url_for("configuracion_sistema"))

    @app.route("/configuracion/respaldo/crear", methods=["POST"])
    @login_required
    def respaldo_crear():
        solo_principal()
        try:
            nombre = crear_respaldo("manual")
            D.registrar_auditoria("SISTEMA", "RESPALDO", nombre)
            db.session.commit()
            flash(f"Respaldo creado: {nombre}", "success")
        except Exception as error:
            flash(str(error), "danger")
        return redirect(url_for("configuracion_sistema"))

    @app.route("/configuracion/respaldo/descargar/<nombre>")
    @login_required
    def respaldo_descargar(nombre):
        solo_principal()
        if not _NOMBRE_VALIDO.match(nombre):
            abort(404)
        return send_from_directory(carpeta_respaldos(), nombre, as_attachment=True)

    @app.route("/configuracion/respaldo/eliminar/<nombre>", methods=["POST"])
    @login_required
    def respaldo_eliminar(nombre):
        solo_principal()
        ruta = os.path.join(carpeta_respaldos(), nombre)
        if not _NOMBRE_VALIDO.match(nombre) or not os.path.isfile(ruta):
            abort(404)
        os.remove(ruta)
        D.registrar_auditoria("SISTEMA", "RESPALDO_ELIMINADO", nombre)
        db.session.commit()
        flash("Respaldo eliminado.", "success")
        return redirect(url_for("configuracion_sistema"))

    @app.route("/configuracion/respaldo/restaurar", methods=["POST"])
    @login_required
    def respaldo_restaurar():
        solo_principal()
        if request.form.get("confirmacion", "").strip() != "RESTAURAR":
            flash("Escribe RESTAURAR para confirmar. No se realizó ningún cambio.", "warning")
            return redirect(url_for("configuracion_sistema"))
        try:
            archivo = request.files.get("archivo")
            if archivo and archivo.filename:
                with tempfile.TemporaryDirectory() as tmp:
                    ruta = os.path.join(tmp, "subido")
                    archivo.save(ruta)
                    restaurar(ruta)
            else:
                nombre = request.form.get("nombre", "")
                ruta = os.path.join(carpeta_respaldos(), nombre)
                if not _NOMBRE_VALIDO.match(nombre) or not os.path.isfile(ruta):
                    raise ValueError("Selecciona un respaldo válido.")
                restaurar(ruta)
            flash("Información restaurada. Se guardó antes un respaldo del estado anterior.", "success")
        except Exception as error:
            db.session.rollback()
            flash(f"No se pudo restaurar: {error}", "danger")
        return redirect(url_for("configuracion_sistema"))

    @app.route("/configuracion/reparar", methods=["POST"])
    @login_required
    def reparar_sistema():
        solo_principal()
        try:
            crear_respaldo("pre_reparacion")
            agregadas = reparar_estructura()
            D.registrar_auditoria("SISTEMA", "REPARAR_ESTRUCTURA", ", ".join(agregadas) or "sin cambios")
            db.session.commit()
            flash(
                "Estructura verificada. "
                + (f"Se agregaron: {', '.join(agregadas)}." if agregadas else "No faltaba nada.")
                + " Tus registros no se modificaron.",
                "success",
            )
        except Exception as error:
            db.session.rollback()
            flash(str(error), "danger")
        return redirect(url_for("configuracion_sistema"))
