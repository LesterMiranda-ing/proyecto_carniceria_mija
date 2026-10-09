"""Acceso a datos del módulo de Autenticación y Usuarios (roles, usuarios y permisos).

Fase 1: inicio de sesión. Fase 2: gestión de usuarios/roles y matriz de permisos por rol.
Fase 3: aplicación de esos permisos a las rutas + excepciones puntuales por usuario
(`usuario_permisos`): un usuario hereda los permisos de su rol y puede tener excepciones
"permitir" (le suman algo que su rol no da) o "denegar" (le quitan algo que su rol sí da).
"""

import re

import psycopg2.errors
from werkzeug.security import generate_password_hash

from app.auth import permisos, seguridad
from app.db import get_db

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS roles (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(50) UNIQUE NOT NULL,
    descripcion     VARCHAR(255),
    es_sistema      BOOLEAN NOT NULL DEFAULT FALSE,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMP NOT NULL DEFAULT NOW()
);
ALTER TABLE roles ADD COLUMN IF NOT EXISTS permisos_sembrados BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS rol_permisos (
    rol_id      INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permiso     VARCHAR(60) NOT NULL,
    PRIMARY KEY (rol_id, permiso)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id                      SERIAL PRIMARY KEY,
    nombre_completo         VARCHAR(150) NOT NULL,
    usuario                 VARCHAR(50) UNIQUE NOT NULL CHECK (usuario = lower(usuario)),
    email                   VARCHAR(150),
    password_hash           VARCHAR(255) NOT NULL,
    rol_id                  INTEGER NOT NULL REFERENCES roles(id),
    activo                  BOOLEAN NOT NULL DEFAULT TRUE,
    debe_cambiar_password   BOOLEAN NOT NULL DEFAULT FALSE,
    ultimo_acceso           TIMESTAMP,
    creado_en               TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS usuario_permisos (
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    permiso     VARCHAR(60) NOT NULL,
    efecto      VARCHAR(10) NOT NULL CHECK (efecto IN ('permitir', 'denegar')),
    PRIMARY KEY (usuario_id, permiso)
);
"""

ROL_GERENTE = "Gerente"
ROL_CARNICERO = "Carnicero"

# es_sistema = no se puede borrar ni renombrar. Gerente además tiene acceso total fijo en código.
ROLES_BASE = (
    {
        "nombre": ROL_GERENTE,
        "descripcion": "Administrador: acceso total a la aplicación, gestión de usuarios, roles y permisos.",
        "es_sistema": True,
    },
    {
        "nombre": ROL_CARNICERO,
        "descripcion": "Rol operativo.",
        "es_sistema": True,
    },
)

# Se verifica contra este hash cuando el usuario no existe, para que responder
# "usuario inexistente" no sea más rápido que responder "contraseña incorrecta".
HASH_FICTICIO = generate_password_hash("contrasena-ficticia-no-usar")


def crear_tabla():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    db.commit()


def sembrar_datos_base(admin_usuario, admin_password, admin_nombre="Administrador"):
    """Garantiza los roles base y, si no hay ningún Gerente activo, crea el primero.

    Devuelve un código de estado para que quien arranca la app pueda registrarlo:
      'ok_creado'            se creó el primer Gerente
      'ya_existe_gerente'    ya había un Gerente activo (no se toca nada)
      'sin_credenciales'     falta ADMIN_USUARIO / ADMIN_PASSWORD en el .env
      'password_invalida'    ADMIN_PASSWORD no cumple la política
      'usuario_en_uso'       ADMIN_USUARIO ya pertenece a otra cuenta
    """
    db = get_db()
    with db.cursor() as cur:
        for rol in ROLES_BASE:
            cur.execute(
                """
                INSERT INTO roles (nombre, descripcion, es_sistema)
                VALUES (%s, %s, %s)
                ON CONFLICT (nombre) DO NOTHING;
                """,
                (rol["nombre"], rol["descripcion"], rol["es_sistema"]),
            )

        # Permisos iniciales del Carnicero: se aplican UNA sola vez. Si luego el Gerente los
        # edita (incluso dejándolos vacíos), un reinicio no los restaura.
        cur.execute("SELECT id, permisos_sembrados FROM roles WHERE nombre = %s;", (ROL_CARNICERO,))
        carnicero = cur.fetchone()
        if carnicero and not carnicero["permisos_sembrados"]:
            for codigo in sorted(permisos.PERMISOS_INICIALES_CARNICERO):
                cur.execute(
                    "INSERT INTO rol_permisos (rol_id, permiso) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                    (carnicero["id"], codigo),
                )
            cur.execute("UPDATE roles SET permisos_sembrados = TRUE WHERE id = %s;", (carnicero["id"],))

        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM usuarios u JOIN roles r ON r.id = u.rol_id
            WHERE r.nombre = %s AND r.es_sistema AND u.activo;
            """,
            (ROL_GERENTE,),
        )
        if cur.fetchone()["total"] > 0:
            db.commit()
            return "ya_existe_gerente"

        admin_usuario = (admin_usuario or "").strip().lower()
        if not admin_usuario or not admin_password:
            db.commit()
            return "sin_credenciales"

        if seguridad.errores_password(admin_password, admin_usuario):
            db.commit()
            return "password_invalida"

        cur.execute("SELECT id FROM usuarios WHERE usuario = %s;", (admin_usuario,))
        if cur.fetchone() is not None:
            db.commit()
            return "usuario_en_uso"

        cur.execute("SELECT id FROM roles WHERE nombre = %s;", (ROL_GERENTE,))
        rol_gerente_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO usuarios (nombre_completo, usuario, password_hash, rol_id, debe_cambiar_password)
            VALUES (%s, %s, %s, %s, TRUE);
            """,
            ((admin_nombre or "Administrador").strip(), admin_usuario,
             generate_password_hash(admin_password), rol_gerente_id),
        )
    db.commit()
    return "ok_creado"


# --- Consultas ---------------------------------------------------------------------

def obtener_roles_activos():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT id, nombre, descripcion FROM roles WHERE activo = TRUE ORDER BY (nombre = %s) DESC, nombre;",
                    (ROL_GERENTE,))
        return cur.fetchall()


def contar_usuarios():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM usuarios;")
        return cur.fetchone()["total"]


_SELECT_USUARIO = """
    SELECT u.id, u.nombre_completo, u.usuario, u.email, u.password_hash, u.rol_id, u.activo,
           u.debe_cambiar_password, u.ultimo_acceso,
           r.nombre AS rol_nombre, r.activo AS rol_activo, r.es_sistema AS rol_es_sistema
    FROM usuarios u
    JOIN roles r ON r.id = u.rol_id
"""


def obtener_usuario_por_login(usuario):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(_SELECT_USUARIO + " WHERE u.usuario = %s;", ((usuario or "").strip().lower(),))
        return cur.fetchone()


def obtener_usuario_activo_por_id(usuario_id):
    """Usuario vigente (cuenta y rol activos) o None. Se consulta en cada petición."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(_SELECT_USUARIO + " WHERE u.id = %s AND u.activo AND r.activo;", (usuario_id,))
        return cur.fetchone()


def registrar_acceso(usuario_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("UPDATE usuarios SET ultimo_acceso = NOW() WHERE id = %s;", (usuario_id,))
    db.commit()


def actualizar_password(usuario_id, password_nueva):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "UPDATE usuarios SET password_hash = %s, debe_cambiar_password = FALSE WHERE id = %s;",
            (generate_password_hash(password_nueva), usuario_id),
        )
    db.commit()


def es_gerente(usuario):
    """True si el usuario (fila de _SELECT_USUARIO) tiene el rol de sistema Gerente."""
    return bool(usuario) and usuario["rol_nombre"] == ROL_GERENTE and bool(usuario["rol_es_sistema"])


def permisos_efectivos(usuario):
    """Conjunto de permisos que el usuario tiene AHORA (se consulta en cada petición).

    Gerente = todo, fijo en código: sus excepciones (si las hubiera) no importan.
    Cualquier otro rol = permisos del rol, más sus "permitir" puntuales, menos sus "denegar".
    """
    if not usuario:
        return frozenset()
    if es_gerente(usuario):
        return permisos.TODOS

    base = obtener_permisos_rol(usuario["rol_id"])
    overrides = obtener_permisos_usuario(usuario["id"])
    permitir = {p for p, efecto in overrides.items() if efecto == "permitir"}
    denegar = {p for p, efecto in overrides.items() if efecto == "denegar"}
    return frozenset((base | permitir) - denegar)


# =====================================================================================
# Fase 2 — Gestión de usuarios
# =====================================================================================

PATRON_USUARIO = re.compile(r"^[a-z0-9._-]{3,50}$")
PATRON_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def contar_gerentes_activos():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM usuarios u JOIN roles r ON r.id = u.rol_id
            WHERE r.nombre = %s AND r.es_sistema AND u.activo AND r.activo;
            """,
            (ROL_GERENTE,),
        )
        return cur.fetchone()["total"]


def listar_usuarios(busqueda=None):
    condiciones, parametros = [], []
    if busqueda:
        condiciones.append("(u.nombre_completo ILIKE %s OR u.usuario ILIKE %s)")
        parametros.extend([f"%{busqueda}%", f"%{busqueda}%"])
    where_sql = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT u.id, u.nombre_completo, u.usuario, u.email, u.rol_id, u.activo,
                   u.debe_cambiar_password, u.ultimo_acceso,
                   r.nombre AS rol_nombre, r.es_sistema AS rol_es_sistema
            FROM usuarios u JOIN roles r ON r.id = u.rol_id
            {where_sql}
            ORDER BY u.activo DESC, u.nombre_completo;
            """,
            parametros or None,
        )
        return cur.fetchall()


def obtener_usuario_por_id(usuario_id):
    """Usuario en cualquier estado (a diferencia de obtener_usuario_activo_por_id)."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(_SELECT_USUARIO + " WHERE u.id = %s;", (usuario_id,))
        return cur.fetchone()


def _validar_datos_usuario(nombre_completo, email):
    nombre_completo = (nombre_completo or "").strip()
    email = (email or "").strip() or None
    if not nombre_completo:
        raise ValueError("El nombre completo es obligatorio.")
    if len(nombre_completo) > 150:
        raise ValueError("El nombre completo es demasiado largo (máximo 150 caracteres).")
    if email and not PATRON_EMAIL.match(email):
        raise ValueError("El correo electrónico no es válido.")
    return nombre_completo, email


def _rol_activo(cur, rol_id):
    cur.execute("SELECT id, nombre, es_sistema FROM roles WHERE id = %s AND activo;", (rol_id,))
    rol = cur.fetchone()
    if rol is None:
        raise ValueError("El rol seleccionado no es válido.")
    return rol


def _es_ultimo_gerente_activo(usuario):
    """True si `usuario` es un Gerente activo y no hay otro: quitarle el acceso dejaría el sistema sin administrador."""
    return es_gerente(usuario) and usuario["activo"] and contar_gerentes_activos() <= 1


def crear_usuario(nombre_completo, usuario, email, password, rol_id):
    """Crea un usuario con contraseña TEMPORAL (debe cambiarla en su primer ingreso)."""
    nombre_completo, email = _validar_datos_usuario(nombre_completo, email)
    usuario = (usuario or "").strip().lower()
    if not PATRON_USUARIO.match(usuario):
        raise ValueError("El usuario debe tener de 3 a 50 caracteres: letras minúsculas, números, punto, guion o guion bajo.")
    errores = seguridad.errores_password(password or "", usuario)
    if errores:
        raise ValueError("Contraseña inicial no válida. " + " ".join(errores))

    db = get_db()
    try:
        with db.cursor() as cur:
            _rol_activo(cur, rol_id)
            cur.execute("SELECT 1 FROM usuarios WHERE usuario = %s;", (usuario,))
            if cur.fetchone() is not None:
                raise ValueError(f"El usuario «{usuario}» ya existe.")
            cur.execute(
                """
                INSERT INTO usuarios (nombre_completo, usuario, email, password_hash, rol_id, debe_cambiar_password)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                RETURNING id;
                """,
                (nombre_completo, usuario, email, generate_password_hash(password), rol_id),
            )
            nuevo_id = cur.fetchone()["id"]
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        raise ValueError(f"El usuario «{usuario}» ya existe.")
    db.commit()
    return nuevo_id


def actualizar_usuario(usuario_id, nombre_completo, email, rol_id, actor_id):
    nombre_completo, email = _validar_datos_usuario(nombre_completo, email)
    objetivo = obtener_usuario_por_id(usuario_id)
    if objetivo is None:
        raise ValueError("El usuario no existe.")
    if rol_id is None:  # el formulario no envió rol (p. ej. te editas a ti mismo): se conserva el actual
        rol_id = objetivo["rol_id"]

    db = get_db()
    with db.cursor() as cur:
        _rol_activo(cur, rol_id)
        if rol_id != objetivo["rol_id"]:
            if usuario_id == actor_id:
                raise ValueError("No puedes cambiar tu propio rol.")
            if _es_ultimo_gerente_activo(objetivo):
                raise ValueError("Debe existir al menos un Gerente activo: primero asigna otro Gerente.")
        cur.execute(
            "UPDATE usuarios SET nombre_completo = %s, email = %s, rol_id = %s WHERE id = %s;",
            (nombre_completo, email, rol_id, usuario_id),
        )
    db.commit()


def cambiar_estado_usuario(usuario_id, activo, actor_id):
    """Activa o desactiva (baja lógica) una cuenta. Nunca se borran usuarios: hay historial que los referencia."""
    objetivo = obtener_usuario_por_id(usuario_id)
    if objetivo is None:
        raise ValueError("El usuario no existe.")
    if not activo:
        if usuario_id == actor_id:
            raise ValueError("No puedes desactivar tu propia cuenta.")
        if _es_ultimo_gerente_activo(objetivo):
            raise ValueError("Debe existir al menos un Gerente activo: no se puede desactivar al último.")

    db = get_db()
    with db.cursor() as cur:
        cur.execute("UPDATE usuarios SET activo = %s WHERE id = %s;", (bool(activo), usuario_id))
    db.commit()


def restablecer_password(usuario_id, password_temporal):
    """El Gerente fija una contraseña temporal; el usuario deberá cambiarla al ingresar."""
    objetivo = obtener_usuario_por_id(usuario_id)
    if objetivo is None:
        raise ValueError("El usuario no existe.")
    errores = seguridad.errores_password(password_temporal or "", objetivo["usuario"])
    if errores:
        raise ValueError("Contraseña temporal no válida. " + " ".join(errores))

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "UPDATE usuarios SET password_hash = %s, debe_cambiar_password = TRUE WHERE id = %s;",
            (generate_password_hash(password_temporal), usuario_id),
        )
    db.commit()


# =====================================================================================
# Fase 2 — Gestión de roles y matriz de permisos
# =====================================================================================

def listar_roles_con_conteo():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.nombre, r.descripcion, r.es_sistema,
                   (SELECT COUNT(*) FROM usuarios u WHERE u.rol_id = r.id) AS total_usuarios,
                   (SELECT COUNT(*) FROM rol_permisos rp WHERE rp.rol_id = r.id) AS total_permisos
            FROM roles r
            WHERE r.activo
            ORDER BY (r.nombre = %s) DESC, r.nombre;
            """,
            (ROL_GERENTE,),
        )
        return cur.fetchall()


def obtener_rol(rol_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT id, nombre, descripcion, es_sistema, activo FROM roles WHERE id = %s;", (rol_id,))
        return cur.fetchone()


def _validar_datos_rol(nombre, descripcion):
    nombre = (nombre or "").strip()
    descripcion = (descripcion or "").strip() or None
    if len(nombre) < 2 or len(nombre) > 50:
        raise ValueError("El nombre del rol debe tener entre 2 y 50 caracteres.")
    if descripcion and len(descripcion) > 255:
        raise ValueError("La descripción es demasiado larga (máximo 255 caracteres).")
    return nombre, descripcion


def crear_rol(nombre, descripcion):
    """Crea un rol SIN permisos: el Gerente se los asigna después en la matriz."""
    nombre, descripcion = _validar_datos_rol(nombre, descripcion)
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1 FROM roles WHERE lower(nombre) = lower(%s);", (nombre,))
            if cur.fetchone() is not None:
                raise ValueError(f"Ya existe un rol llamado «{nombre}».")
            cur.execute(
                "INSERT INTO roles (nombre, descripcion, es_sistema, permisos_sembrados) VALUES (%s, %s, FALSE, TRUE) RETURNING id;",
                (nombre, descripcion),
            )
            nuevo_id = cur.fetchone()["id"]
    except psycopg2.errors.UniqueViolation:
        db.rollback()
        raise ValueError(f"Ya existe un rol llamado «{nombre}».")
    db.commit()
    return nuevo_id


def actualizar_rol(rol_id, nombre, descripcion):
    rol = obtener_rol(rol_id)
    if rol is None:
        raise ValueError("El rol no existe.")
    nombre, descripcion = _validar_datos_rol(nombre, descripcion)
    if rol["es_sistema"] and nombre != rol["nombre"]:
        raise ValueError("Los roles del sistema no se pueden renombrar.")

    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM roles WHERE lower(nombre) = lower(%s) AND id <> %s;", (nombre, rol_id))
        if cur.fetchone() is not None:
            raise ValueError(f"Ya existe un rol llamado «{nombre}».")
        cur.execute("UPDATE roles SET nombre = %s, descripcion = %s WHERE id = %s;", (nombre, descripcion, rol_id))
    db.commit()


def eliminar_rol(rol_id):
    rol = obtener_rol(rol_id)
    if rol is None:
        raise ValueError("El rol no existe.")
    if rol["es_sistema"]:
        raise ValueError("Los roles del sistema no se pueden eliminar.")

    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM usuarios WHERE rol_id = %s;", (rol_id,))
        if cur.fetchone()["total"] > 0:
            raise ValueError("No se puede eliminar un rol que tiene usuarios asignados: reasígnalos primero.")
        cur.execute("DELETE FROM roles WHERE id = %s;", (rol_id,))
    db.commit()


def obtener_permisos_rol(rol_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT permiso FROM rol_permisos WHERE rol_id = %s;", (rol_id,))
        return {fila["permiso"] for fila in cur.fetchall()}


def guardar_permisos_rol(rol_id, codigos):
    """Reemplaza, en una sola transacción, los permisos del rol. Devuelve los permisos realmente guardados."""
    rol = obtener_rol(rol_id)
    if rol is None:
        raise ValueError("El rol no existe.")
    if rol["nombre"] == ROL_GERENTE and rol["es_sistema"]:
        raise ValueError("El rol Gerente tiene acceso total y no se puede restringir.")

    finales = permisos.normalizar(codigos)
    db = get_db()
    with db.cursor() as cur:
        cur.execute("DELETE FROM rol_permisos WHERE rol_id = %s;", (rol_id,))
        for codigo in sorted(finales):
            cur.execute("INSERT INTO rol_permisos (rol_id, permiso) VALUES (%s, %s);", (rol_id, codigo))
    db.commit()
    return finales


# =====================================================================================
# Fase 3b — Excepciones de permisos por usuario (permitir / denegar sobre lo que da su rol)
# =====================================================================================

def obtener_permisos_usuario(usuario_id):
    """{permiso: 'permitir'|'denegar'} — solo las EXCEPCIONES del usuario, no lo heredado del rol."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT permiso, efecto FROM usuario_permisos WHERE usuario_id = %s;", (usuario_id,))
        return {fila["permiso"]: fila["efecto"] for fila in cur.fetchall()}


def obtener_excepciones_multiples(usuario_ids):
    """{usuario_id: {permiso: efecto}} para varios usuarios a la vez (pantalla de listado)."""
    usuario_ids = list(usuario_ids)
    if not usuario_ids:
        return {}
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT usuario_id, permiso, efecto FROM usuario_permisos WHERE usuario_id = ANY(%s);", (usuario_ids,))
        resultado = {}
        for fila in cur.fetchall():
            resultado.setdefault(fila["usuario_id"], {})[fila["permiso"]] = fila["efecto"]
        return resultado


def guardar_permisos_usuario(usuario_id, permitir, denegar):
    """Reemplaza, en una sola transacción, las excepciones del usuario.

    `permitir`/`denegar` son iterables de códigos de permiso. Un código presente en
    ambos (no debería ocurrir desde la UI, que es de un solo valor por permiso) se
    resuelve a favor de "denegar", para fallar cerrado ante datos contradictorios.
    "permitir" se normaliza igual que en un rol (marcar una acción también permite ver
    su módulo); "denegar" se toma tal cual, sin esa expansión.
    """
    objetivo = obtener_usuario_por_id(usuario_id)
    if objetivo is None:
        raise ValueError("El usuario no existe.")
    if es_gerente(objetivo):
        raise ValueError("El Gerente tiene acceso total: no se le pueden configurar excepciones.")

    denegar_final = {c for c in (denegar or ()) if c in permisos.TODOS}
    permitir_final = permisos.normalizar(permitir) - denegar_final

    db = get_db()
    with db.cursor() as cur:
        cur.execute("DELETE FROM usuario_permisos WHERE usuario_id = %s;", (usuario_id,))
        for codigo in sorted(permitir_final):
            cur.execute(
                "INSERT INTO usuario_permisos (usuario_id, permiso, efecto) VALUES (%s, %s, 'permitir');",
                (usuario_id, codigo),
            )
        for codigo in sorted(denegar_final):
            cur.execute(
                "INSERT INTO usuario_permisos (usuario_id, permiso, efecto) VALUES (%s, %s, 'denegar');",
                (usuario_id, codigo),
            )
    db.commit()
    return permitir_final, denegar_final
