from flask import Blueprint, g, render_template

from app.auth import permisos
from app.dashboard import models

dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/dashboard",
    template_folder="../templates",
)


@dashboard_bp.route("/", methods=["GET"])
def inicio():
    # El acceso al Dashboard no implica ver todo su contenido: cada bloque exige el permiso
    # de SU módulo, y sin ese permiso ni siquiera se consulta el dato.
    def puede(permiso):
        return permisos.permite(g.permisos, permiso)

    ver_finanzas = puede("finanzas.ver")
    ver_ventas = puede("pos.ver")
    ver_stock = puede("inventario.ver")

    return render_template(
        "dashboard/inicio.html",
        resumen=models.obtener_resumen_hoy() if ver_finanzas else None,
        flujo=models.obtener_flujo_caja_semana() if ver_finanzas else None,
        alertas=models.obtener_alertas_stock(limite=5) if ver_stock else None,
        movimientos=models.obtener_ultimos_movimientos(limite=6) if ver_ventas else None,
    )
