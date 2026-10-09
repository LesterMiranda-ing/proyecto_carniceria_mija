# Carnicería La Mija — Sistema de Gestión e Inventario

Aplicación web para una carnicería: entrada de canales, desposte y control de merma, inventario,
punto de venta, clientes, proveedores, finanzas, dashboard, usuarios con roles y permisos, y bitácora
de auditoría.

**Tecnología:** Python + Flask (un Blueprint por módulo), PostgreSQL con SQL directo (psycopg2, sin ORM),
HTML con Jinja y Tailwind (CDN) y JavaScript sin frameworks.

## Módulos

- **Entrada de canal:** registro de cada canal que llega (proveedor, peso, costo) con su historial.
- **Desposte:** cortes obtenidos, tara, rendimiento y merma; genera el stock vendible.
- **Inventario:** catálogo de productos con precios de detalle y mayoreo, y alertas de bajo stock.
- **Punto de venta:** ventas por peso o unidad, control de stock en tiempo real y recibo.
- **Clientes y proveedores:** directorios con búsqueda.
- **Finanzas:** gastos operativos y cuadre diario de ventas.
- **Dashboard:** resumen del día, flujo de caja de la semana y alertas de stock.
- **Usuarios, roles y permisos:** control de acceso por módulo y por acción.
- **Auditoría:** bitácora de quién hizo qué (solo el Gerente).
- **Reportes:** impresión/PDF en cada pantalla y descarga a Excel en los listados.

## Cómo correrlo en tu máquina

1. Instala **Python 3.10 o superior**, **PostgreSQL** y **Git**.
2. Crea una base de datos vacía llamada `carniceria_mija` en PostgreSQL. Las tablas las crea la
   aplicación sola al arrancar.
3. En la carpeta del proyecto, crea el entorno virtual e instala las dependencias:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

4. Copia `.env.example` como `.env` y completa tus datos (usuario y contraseña de PostgreSQL, `SECRET_KEY`
   y el primer administrador `ADMIN_USUARIO` / `ADMIN_PASSWORD`). **El `.env` nunca se sube a GitHub.**
5. Arranca la aplicación y entra a `http://127.0.0.1:5000`:

```
python run.py
```

Con el servidor corriendo, los cambios en archivos HTML se ven al recargar la página; los cambios en
archivos `.py` requieren detener el servidor (Ctrl+C) y volver a correr `python run.py`.

## Estructura

```
run.py                     arranque de la aplicación
app/__init__.py            registra los módulos y crea las tablas
app/config.py, app/db.py   configuración y conexión a PostgreSQL
app/auth/                  login, usuarios, roles y permisos
app/inventario/            entrada de canal, desposte, productos y proveedores
app/ventas/                punto de venta, clientes e historial de ventas
app/finanzas/              gastos y cuadre de ventas
app/dashboard/             panel principal
app/auditoria/             bitácora de quién hizo qué (solo Gerente)
app/comun/                 utilidades compartidas (reportes Excel, avisos de stock)
app/templates/<módulo>/    pantallas HTML de cada módulo
```
