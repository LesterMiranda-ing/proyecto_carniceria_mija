"""Avisos por WhatsApp mediante CallMeBot (servicio gratuito, NO oficial, solo para uso personal).

Reglas de diseño:
  - Nunca debe romper ni retrasar una venta: el envío corre en un hilo aparte con timeout
    corto y cualquier fallo solo se registra en el log.
  - Si CALLMEBOT_PHONE / CALLMEBOT_APIKEY no están configurados, no hace nada.
  - La apikey viaja en la URL de CallMeBot, así que NUNCA se escribe en el log.

Prueba manual (envía un mensaje real):  python -m app.comun.notificaciones
"""

import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from flask import current_app

log = logging.getLogger(__name__)

URL_CALLMEBOT = "https://api.callmebot.com/whatsapp.php"
TIMEOUT_SEGUNDOS = 20  # CallMeBot a veces tarda; corre en segundo plano, así que no frena la venta
MAX_PRODUCTOS_POR_AVISO = 10


def _lanzar(tarea):
    """Ejecuta `tarea` sin bloquear la petición web (las pruebas lo sustituyen por una llamada directa)."""
    threading.Thread(target=tarea, daemon=True).start()


def _http_get(url):
    """Hace la petición y devuelve el código HTTP (las pruebas lo sustituyen para no enviar nada real)."""
    with urllib.request.urlopen(url, timeout=TIMEOUT_SEGUNDOS) as respuesta:
        return respuesta.status


def _normalizar_telefono(telefono):
    """Deja solo '+' inicial (si lo hay) y dígitos: '+502 1234-5678' -> '+50212345678'."""
    telefono = (telefono or "").strip()
    digitos = re.sub(r"\D", "", telefono)
    return ("+" if telefono.startswith("+") else "") + digitos


def construir_url(telefono, apikey, texto):
    consulta = urllib.parse.urlencode({"phone": _normalizar_telefono(telefono), "text": texto, "apikey": apikey})
    return f"{URL_CALLMEBOT}?{consulta}"


def whatsapp_configurado():
    return bool(current_app.config.get("CALLMEBOT_PHONE") and current_app.config.get("CALLMEBOT_APIKEY"))


def enviar_whatsapp(texto, al_fallar=None):
    """Despacha el mensaje en segundo plano. Devuelve True si se despachó (no garantiza la entrega).

    `al_fallar` (opcional) se ejecuta, con contexto de aplicación, si el envío falla: sirve para
    deshacer la marca de "ya avisado" y que el siguiente intento no espere horas.
    """
    if not whatsapp_configurado():
        return False

    url = construir_url(current_app.config["CALLMEBOT_PHONE"], current_app.config["CALLMEBOT_APIKEY"], texto)
    app = current_app._get_current_object()

    def tarea():
        exito = False
        try:
            codigo = _http_get(url)
            if codigo == 200:
                exito = True
                log.info("Aviso de stock enviado a CallMeBot.")
            else:
                log.warning("CallMeBot respondió HTTP %s al enviar el aviso de stock.", codigo)
        except urllib.error.HTTPError as exc:
            log.warning("CallMeBot rechazó el aviso de stock: HTTP %s.", exc.code)
        except Exception as exc:  # red caída, timeout, DNS...: la venta ya está hecha, solo se registra
            log.warning("No se pudo enviar el aviso de stock por WhatsApp: %s", type(exc).__name__)

        if not exito and al_fallar:
            try:
                with app.app_context():
                    al_fallar()
            except Exception as exc:
                log.warning("No se pudo reiniciar el control de avisos: %s", type(exc).__name__)

    _lanzar(tarea)
    return True


def redactar_aviso_stock(alertas, numero_venta=None):
    lineas = ["*ALERTA DE STOCK - Carnicería La Mija*"]
    if numero_venta:
        lineas.append(f"Tras la venta {numero_venta}:")
    for a in alertas[:MAX_PRODUCTOS_POR_AVISO]:
        nivel = "CRITICO" if a["critico"] else "Bajo"
        lineas.append(
            f"- {a['nombre']}: quedan {a['stock_actual']:.2f} {a['unidad_venta']} "
            f"(mínimo {a['stock_minimo']:.2f}) - {nivel}"
        )
    if len(alertas) > MAX_PRODUCTOS_POR_AVISO:
        lineas.append(f"... y {len(alertas) - MAX_PRODUCTOS_POR_AVISO} producto(s) más.")
    return "\n".join(lineas)


def notificar_bajo_stock(alertas, numero_venta=None, al_fallar=None):
    """Avisa por WhatsApp de los productos con `avisar=True` (ya filtrados por el control de espera).

    `al_fallar(ids_de_productos)` se llama si el envío falla.
    """
    a_avisar = [a for a in alertas if a.get("avisar")]
    if not a_avisar:
        return False
    ids = [a["producto_id"] for a in a_avisar]
    return enviar_whatsapp(
        redactar_aviso_stock(a_avisar, numero_venta),
        al_fallar=(lambda: al_fallar(ids)) if al_fallar else None,
    )


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        if not whatsapp_configurado():
            raise SystemExit("Falta CALLMEBOT_PHONE y/o CALLMEBOT_APIKEY en el .env.")
        url = construir_url(app.config["CALLMEBOT_PHONE"], app.config["CALLMEBOT_APIKEY"],
                            "Prueba de avisos de Carnicería La Mija: si lees esto, CallMeBot funciona.")
        try:
            print("Respuesta de CallMeBot: HTTP", _http_get(url))
            print("Revisa tu WhatsApp (puede tardar unos segundos).")
        except urllib.error.HTTPError as exc:
            print(f"CallMeBot rechazó la petición: HTTP {exc.code}. Revisa teléfono y apikey.")
        except Exception as exc:
            print("No se pudo contactar a CallMeBot:", type(exc).__name__)
