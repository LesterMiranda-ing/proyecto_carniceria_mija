import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuración global de la aplicación (leída desde variables de entorno)."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "5432")
    DB_NAME = os.environ.get("DB_NAME", "carniceria_mija")
    DB_USER = os.environ.get("DB_USER", "postgres")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")

    # Primer Gerente: se crea automáticamente al arrancar SOLO si todavía no existe
    # ningún Gerente activo. Su contraseña es temporal (se obliga a cambiarla al
    # primer ingreso); después conviene borrar ADMIN_PASSWORD del .env.
    ADMIN_USUARIO = os.environ.get("ADMIN_USUARIO", "")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    ADMIN_NOMBRE = os.environ.get("ADMIN_NOMBRE", "Administrador")

    # Avisos de bajo stock por WhatsApp vía CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/).
    # Si falta alguno de los dos, simplemente no se envía nada (la alerta en pantalla sigue funcionando).
    CALLMEBOT_PHONE = os.environ.get("CALLMEBOT_PHONE", "")
    CALLMEBOT_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "")
    # Horas mínimas entre dos avisos del mismo producto (para no recibir uno por cada venta).
    ALERTA_STOCK_HORAS = int(os.environ.get("ALERTA_STOCK_HORAS", "6") or 6)

    # Sesión: cookie firmada, no accesible desde JS y no enviada en peticiones cross-site.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
