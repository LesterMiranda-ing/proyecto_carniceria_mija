from app import create_app
from flask_cloudflared import run_with_cloudflared

app = create_app()

if __name__ == "__main__":
    run_with_cloudflared(app)
    # debug=True: las plantillas HTML se recargan solas (ya no hace falta Ctrl+C para verlas).
    # use_reloader=False: evita que Flask reinicie el proceso en un subproceso, lo que
    # duplicaría el túnel de Cloudflare abierto arriba. Los cambios en archivos .py siguen
    # necesitando Ctrl+C + volver a correr `python run.py`.
    app.run(debug=True, use_reloader=False)
