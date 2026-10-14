"""Pantalla de Auditoría (solo Gerente): consulta filtrable de la bitácora y descarga a Excel."""

import json
from datetime import datetime

from flask import Blueprint, g, render_template, request

from app.auditoria import models
from app.auth import models as modelos_auth
from app.auth.routes import _rechazar, destino_inicio
from app.comun.excel import respuesta_excel

auditoria_bp = Blueprint(
    "auditoria",
    __name__,
    url_prefix="/auditoria",
    template_folder="../templates",
)

POR_PAGINA = 25


@auditoria_bp.before_request
def solo_gerente():
    """La bitácora no es delegable: solo el rol de sistema Gerente entra."""
    if not modelos_auth.es_gerente(getattr(g, "usuario", None)):
        return _rechazar("No tienes permiso para acceder a la Auditoría.", 403, destino_inicio())
    return None


def _fecha(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return None


def _filtros_de_la_peticion():
    accion = request.args.get("accion", "")
    return {
        "desde": _fecha(request.args.get("desde")),
        "hasta": _fecha(request.args.get("hasta")),
        "usuario_id": request.args.get("usuario_id", type=int),
        "accion": accion if accion in models.ACCIONES else None,
        "q": (request.args.get("q") or "").strip()[:100] or None,
        "solo_sensibles": request.args.get("sensibles") == "1",
    }


@auditoria_bp.route("/", methods=["GET"])
def registro():
    filtros = _filtros_de_la_peticion()
    pagina = max(request.args.get("pagina", 1, type=int), 1)
    registros, total = models.listar(filtros, pagina=pagina, por_pagina=POR_PAGINA)

    # Parámetros que se conservan al paginar y al exportar.
    parametros = {k: v for k, v in {
        "desde": filtros["desde"], "hasta": filtros["hasta"], "usuario_id": filtros["usuario_id"],
        "accion": filtros["accion"], "q": filtros["q"], "sensibles": "1" if filtros["solo_sensibles"] else None,
    }.items() if v}

    return render_template(
        "auditoria/registro.html",
        registros=registros,
        total=total,
        pagina=pagina,
        total_paginas=max((total + POR_PAGINA - 1) // POR_PAGINA, 1),
        por_pagina=POR_PAGINA,
        filtros=filtros,
        parametros=parametros,
        acciones=models.ACCIONES,
        sensibles=models.ACCIONES_SENSIBLES,
        usuarios=models.usuarios_con_registros(),
    )


@auditoria_bp.route("/excel", methods=["GET"])
def exportar_excel():
    registros, _total = models.listar(_filtros_de_la_peticion(), pagina=1, por_pagina=1_000_000)
    filas = [
        (
            r["creado_en"].strftime("%d/%m/%Y %H:%M:%S"), r["usuario_nombre"] or "(sin sesión)",
            models.ACCIONES.get(r["accion"], r["accion"]), r["descripcion"], r["entidad"] or "",
            r["entidad_id"] or "", r["ip"] or "",
            json.dumps(r["detalle"], ensure_ascii=False) if r["detalle"] else "",
        )
        for r in registros
    ]
    return respuesta_excel(
        "auditoria.xlsx", "Auditoría",
        ["Fecha", "Usuario", "Acción", "Descripción", "Entidad", "ID", "IP", "Detalle"],
        filas,
    )
