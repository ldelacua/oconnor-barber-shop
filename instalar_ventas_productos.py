"""Ejecutar desde la raíz del proyecto: python instalar_ventas_productos.py"""
import ast
from pathlib import Path
from datetime import datetime
import shutil

RAIZ = Path(__file__).resolve().parent

def integrar():
    settings = RAIZ / "config/settings.py"
    urls = RAIZ / "config/urls.py"
    base = RAIZ / "templates/base.html"
    cambios = {}
    texto = settings.read_text(encoding="utf-8-sig")
    arbol = ast.parse(texto)
    if not any(isinstance(n, ast.Constant) and isinstance(n.value, str) and
               n.value in ("ventas_productos", "ventas_productos.apps.VentasProductosConfig") for n in ast.walk(arbol)):
        nodo = next(n for n in arbol.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == "INSTALLED_APPS" for t in n.targets))
        if not isinstance(nodo.value, ast.List):
            raise RuntimeError("INSTALLED_APPS no es una lista. No se modificó la configuración.")
        lineas = texto.splitlines(keepends=True)
        if nodo.value.lineno == nodo.value.end_lineno:
            raise RuntimeError("La lista INSTALLED_APPS debe ocupar varias líneas.")
        lineas.insert(nodo.value.lineno, "    'ventas_productos.apps.VentasProductosConfig',\n")
        cambios[settings] = "".join(lineas)
    texto = urls.read_text(encoding="utf-8-sig")
    if 'include("ventas_productos.urls")' not in texto and "include('ventas_productos.urls')" not in texto:
        arbol = ast.parse(texto)
        nodo = next(n for n in arbol.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == "urlpatterns" for t in n.targets))
        if not isinstance(nodo.value, ast.List) or nodo.value.lineno == nodo.value.end_lineno:
            raise RuntimeError("urlpatterns debe ser una lista de varias líneas.")
        lineas = texto.splitlines(keepends=True)
        lineas.insert(nodo.value.lineno, '    path("ventas-productos/", include("ventas_productos.urls")),\n')
        cambios[urls] = "".join(lineas)
    texto = base.read_text(encoding="utf-8-sig")
    if "ventas_productos:lista" not in texto:
        posicion = texto.find('<a href="{% url \'gastos:inicio\' %}"')
        if posicion < 0:
            raise RuntimeError("No se encontró el acceso a Gastos en templates/base.html. No se escribió ningún cambio.")
        enlace = """<a href="{% url 'ventas_productos:lista' %}" class="list-group-item list-group-item-action {% if request.resolver_match.namespace == 'ventas_productos' %}active{% endif %}"><i class="bi bi-bag-check me-1"></i>Venta de productos</a>
"""
        cambios[base] = texto[:posicion] + enlace + texto[posicion:]
    for archivo, contenido in cambios.items():
        if archivo.suffix == ".py":
            ast.parse(contenido)
    if not cambios:
        print("Venta de productos ya está integrado. No se modificaron archivos.")
        return
    respaldo = RAIZ / ("respaldo_integracion_ventas_productos_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    for archivo in cambios:
        destino = respaldo / archivo.relative_to(RAIZ)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archivo, destino)
    try:
        for archivo, contenido in cambios.items():
            archivo.write_text(contenido, encoding="utf-8")
    except Exception:
        for archivo in cambios:
            shutil.copy2(respaldo / archivo.relative_to(RAIZ), archivo)
        raise
    print("Venta de productos integrado. Respaldo de configuración:", respaldo.name)
    print("Ejecuta manage.py check y manage.py migrate con tu entorno virtual.")

if __name__ == "__main__":
    integrar()
