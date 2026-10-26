from app import db

def registrar_auditoria(modulo, accion, descripcion=""):
    try:
        from flask_login import current_user
        from app import Auditoria
        if not current_user.is_authenticated:
            return
        auditoria = Auditoria(
            usuario_id=current_user.id,
            modulo=modulo,
            accion=accion,
            descripcion=descripcion
        )
        db.session.add(auditoria)
    except Exception as e:
        print(f"Error auditoria: {e}")