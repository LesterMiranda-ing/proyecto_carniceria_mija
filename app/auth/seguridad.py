"""Utilidades de seguridad del módulo de autenticación: CSRF, contraseñas y redirecciones."""

import hmac
import re
import secrets
from urllib.parse import urlparse

from flask import session

LONGITUD_MINIMA_PASSWORD = 8


# --- CSRF ------------------------------------------------------------------------
# El token vive en la sesión (cookie firmada). Los formularios lo reciben como campo
# oculto `csrf_token` y los `fetch` como header `X-CSRF-Token`; ambos los inyecta
# automáticamente el layout base, así que un formulario nuevo queda protegido sin
# tener que acordarse de añadirlo.

def obtener_token_csrf():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def token_csrf_valido(peticion):
    esperado = session.get("csrf_token")
    if not esperado:
        return False
    recibido = peticion.headers.get("X-CSRF-Token") or peticion.form.get("csrf_token") or ""
    return hmac.compare_digest(esperado, recibido)


# --- Contraseñas -------------------------------------------------------------------

def errores_password(password, usuario=None):
    """Devuelve la lista de razones por las que la contraseña no cumple la política."""
    errores = []
    if len(password) < LONGITUD_MINIMA_PASSWORD:
        errores.append(f"Debe tener al menos {LONGITUD_MINIMA_PASSWORD} caracteres.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errores.append("Debe combinar letras y números.")
    if usuario and password.strip().lower() == usuario.strip().lower():
        errores.append("No puede ser igual al nombre de usuario.")
    return errores


# --- Redirecciones --------------------------------------------------------------------

def url_segura(destino):
    """Acepta solo rutas internas ("/algo"); evita redirecciones abiertas tipo "//sitio-malo.com"."""
    if not destino or not destino.startswith("/") or destino.startswith("//") or "\\" in destino:
        return None
    partes = urlparse(destino)
    if partes.scheme or partes.netloc:
        return None
    return destino
