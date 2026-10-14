"""Bitácora de auditoría: quién hizo qué y cuándo (tabla `auditoria`). Solo la consulta el Gerente.

Reglas:
  - `registrar()` se llama DESPUÉS de que la acción ya tuvo éxito y nunca debe romperla: si el
    registro falla, se anota en el log del servidor y la operación del usuario sigue como si nada.
  - Jamás se guardan contraseñas, apikeys ni tokens (ver los `detalle` que arman las rutas).
  - `usuario_nombre` es una copia del nombre al momento de la acción: si luego se renombra o se
    borra el usuario, la bitácora conserva lo que pasó.
"""

import json
import logging
import re

from flask import g, has_request_context, request
from psycopg2.extras import Json

from app.db import get_db

log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS auditoria (
    id              BIGSERIAL PRIMARY KEY,
    creado_en       TIMESTAMP NOT NULL DEFAULT NOW(),
    usuario_id      INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    usuario_nombre  VARCHAR(150),
    accion          VARCHAR(40) NOT NULL,
    entidad         VARCHAR(30),
    entidad_id      INTEGER,
    descripcion     VARCHAR(300) NOT NULL,
    detalle         JSONB,
    ip              VARCHAR(45)
);
CREATE INDEX IF NOT EXISTS idx_auditoria_creado_en ON auditoria (creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria (usuario_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_accion ON auditoria (accion);
"""

# código de acción -> etiqueta que ve el Gerente
ACCIONES = {
    "login": "Inicio de sesión",
    "login_fallido": "Inicio de sesión fallido",
    "logout": "Cierre de sesión",
    "password_cambiada": "Cambio de contraseña",
    "password_restablecida": "Contraseña restablecida",
    "usuario_creado": "Usuario creado",
    "usuario_editado": "Usuario editado",
    "usuario_estado": "Usuario activado/desactivado",
    "usuario_permisos": "Excepciones de permisos de usuario",
    "rol_creado": "Rol creado",
    "rol_editado": "Rol editado",
    "rol_eliminado": "Rol eliminado",
    "rol_permisos": "Permisos de rol",
    "entrada_canal_creada": "Entrada de canal registrada",
    "desposte_creado": "Desposte registrado",
    "proveedor_creado": "Proveedor creado",
    "proveedor_editado": "Proveedor editado",
    "proveedor_eliminado": "Proveedor eliminado",
    "producto_creado": "Producto creado",
    "producto_editado": "Producto editado",
    "venta_creada": "Venta registrada",
    "cliente_creado": "Cliente creado",
    "cliente_editado": "Cliente editado",
    "cliente_eliminado": "Cliente eliminado",
    "egreso_creado": "Gasto registrado",
    "egreso_eliminado": "Gasto eliminado",
}

# Se resaltan en rojo en la pantalla: borrados, accesos fallidos y cambios de seguridad.
ACCIONES_SENSIBLES = frozenset({
    "login_fallido", "password_restablecida", "usuario_estado", "usuario_permisos", "rol_permisos",
    "rol_eliminado", "cliente_eliminado", "egreso_eliminado", "proveedor_eliminado",
})

_FORMATO_USUARIO = re.compile(r"^[a-z0-9._-]{1,40}$")


def crear_tabla():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    db.commit()


def _ip_del_cliente():
    """IP del cliente. Detrás de un proxy/túnel (Cloudflare, Railway) la real viene en cabeceras."""
    cabecera = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For") or ""
    ip = cabecera.split(",")[0].strip() or (request.remote_addr or "")
    return ip[:45] or None


def usuario_valido_para_bitacora(texto):
    """Un 'usuario' mal escrito puede ser una contraseña tecleada en el campo equivocado: solo se
    guarda si tiene forma de nombre de usuario."""
    texto = (texto or "").strip().lower()
    return texto if _FORMATO_USUARIO.match(texto) else "(formato no válido)"


def cambios(antes, despues, campos):
    """{campo: {"antes": x, "despues": y}} solo para lo que realmente cambió (None y '' son lo mismo)."""
    def norm(valor):
        if valor is None or valor == "":
            return None
        try:
            return str(float(valor)) if not isinstance(valor, bool) else valor
        except (TypeError, ValueError):
            return str(valor).strip()

    resultado = {}
    for campo in campos:
        if norm(antes.get(campo)) != norm(despues.get(campo)):
            resultado[campo] = {"antes": _a_json(antes.get(campo)), "despues": _a_json(despues.get(campo))}
    return resultado


def _a_json(valor):
    return None if valor is None else (float(valor) if hasattr(valor, "quantize") else valor)


def registrar(accion, descripcion, entidad=None, entidad_id=None, detalle=None, usuario=None):
    """Anota una acción en la bitácora. `usuario` explícito para cuando aún no hay sesión (login)."""
    try:
        if usuario is None and has_request_context():
            usuario = getattr(g, "usuario", None)
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auditoria
                    (usuario_id, usuario_nombre, accion, entidad, entidad_id, descripcion, detalle, ip)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    usuario["id"] if usuario else None,
                    usuario["nombre_completo"] if usuario else None,
                    accion, entidad, entidad_id, descripcion[:300],
                    Json(detalle, dumps=lambda o: json.dumps(o, default=str, ensure_ascii=False)) if detalle else None,
                    _ip_del_cliente() if has_request_context() else None,
                ),
            )
        db.commit()
    except Exception as exc:  # la bitácora nunca debe romper la acción del usuario
        log.warning("No se pudo registrar en la auditoría (%s): %s", accion, type(exc).__name__)
        try:
            get_db().rollback()
        except Exception:
            pass


# --- Consulta (pantalla del Gerente) ----------------------------------------------------

def _condiciones(filtros):
    condiciones, parametros = [], []
    if filtros.get("desde"):
        condiciones.append("a.creado_en >= %s")
        parametros.append(filtros["desde"])
    if filtros.get("hasta"):
        condiciones.append("a.creado_en < (%s::date + 1)")
        parametros.append(filtros["hasta"])
    if filtros.get("usuario_id"):
        condiciones.append("a.usuario_id = %s")
        parametros.append(filtros["usuario_id"])
    if filtros.get("accion"):
        condiciones.append("a.accion = %s")
        parametros.append(filtros["accion"])
    if filtros.get("solo_sensibles"):
        condiciones.append("a.accion = ANY(%s)")
        parametros.append(sorted(ACCIONES_SENSIBLES))
    if filtros.get("q"):
        condiciones.append("(a.descripcion ILIKE %s OR a.usuario_nombre ILIKE %s)")
        parametros.extend([f"%{filtros['q']}%", f"%{filtros['q']}%"])
    return (f"WHERE {' AND '.join(condiciones)}" if condiciones else ""), parametros


def listar(filtros, pagina=1, por_pagina=25):
    donde, parametros = _condiciones(filtros)
    db = get_db()
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM auditoria a {donde};", parametros)
        total = cur.fetchone()["total"]
        cur.execute(
            f"""
            SELECT a.id, a.creado_en, a.usuario_id, a.usuario_nombre, a.accion, a.entidad, a.entidad_id,
                   a.descripcion, a.detalle, a.ip
            FROM auditoria a
            {donde}
            ORDER BY a.creado_en DESC, a.id DESC
            LIMIT %s OFFSET %s;
            """,
            parametros + [por_pagina, (pagina - 1) * por_pagina],
        )
        return cur.fetchall(), total


def usuarios_con_registros():
    """Para el filtro por usuario: quienes aparecen en la bitácora (con el nombre de la copia)."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT usuario_id AS id, MAX(usuario_nombre) AS nombre
            FROM auditoria
            WHERE usuario_id IS NOT NULL
            GROUP BY usuario_id
            ORDER BY MAX(usuario_nombre);
            """
        )
        return cur.fetchall()
