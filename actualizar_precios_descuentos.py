"""Ejecutar desde la raíz del proyecto."""
from pathlib import Path
from datetime import datetime
import re,shutil
def actualizar():
    raiz=Path(__file__).resolve().parent
    archivo=raiz/"templates/base.html"
    texto=archivo.read_text(encoding="utf-8-sig")
    patron=r'(<a\b[^>]*href="\{%\s*url\s+\x27inventario:compras\x27\s*%\}"[^>]*>)(.*?)(</a>)'
    encontrado=False
    def cambiar(m):
        nonlocal encontrado
        encontrado=True
        return m[1]+re.sub(r"\bInventario\b","Compras",m[2])+m[3]
    nuevo=re.sub(patron,cambiar,texto,flags=re.S)
    if not encontrado:raise RuntimeError("No se encontró el acceso a Compras/Inventario en templates/base.html.")
    if nuevo!=texto:
        respaldo=archivo.with_name("base_antes_precios_"+datetime.now().strftime("%Y%m%d_%H%M%S")+".html")
        shutil.copy2(archivo,respaldo);archivo.write_text(nuevo,encoding="utf-8")
        print("Menú actualizado a Compras. Respaldo:",respaldo.name)
    else:print("El menú ya muestra Compras.")
    print("Ejecuta manage.py check y manage.py migrate. Configura porcentajes antes de vender.")
if __name__=="__main__":actualizar()
