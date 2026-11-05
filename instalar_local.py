from datetime import datetime
from pathlib import Path
import shutil

raiz = Path.cwd()
if not (raiz / "manage_mysql.py").is_file():
    raise SystemExit("Ejecuta desde la carpeta del proyecto.")
origen = Path(__file__).resolve().parent
archivos = {p.relative_to(origen): p.read_bytes() for p in origen.rglob("*") if p.is_file() and p.suffix in {".py", ".html"} and p != Path(__file__).resolve()}
ruta = Path("config/urls.py")
codigo = (raiz / ruta).read_text(encoding="utf-8")
if "clientes.portal_urls" not in codigo:
    if codigo.count("urlpatterns = [") != 1 or "import include" not in codigo:
        raise SystemExit("No se reconoció config/urls.py; no se hicieron cambios.")
    codigo = codigo.replace("urlpatterns = [", 'urlpatterns = [\n    path("reservas/", include("clientes.portal_urls")),', 1)
archivos[ruta] = codigo.encode()
for nombre, datos in archivos.items():
    if nombre.suffix == ".py":
        compile(datos, str(nombre), "exec")
respaldo = raiz.parent / ("respaldo_cambios_local_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
for nombre in archivos:
    destino = raiz / nombre
    if destino.is_file():
        copia = respaldo / nombre
        copia.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destino, copia)
for nombre, datos in archivos.items():
    destino = raiz / nombre
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
print("Archivos instalados. Respaldo:", respaldo)
