"""Activa el control de permisos sin reemplazar settings ni credenciales."""
import ast
from pathlib import Path
from datetime import datetime
import shutil


def instalar(raiz=None):
    raiz=Path(raiz) if raiz else Path(__file__).resolve().parent
    ruta=raiz/'config'/'settings.py'
    texto=ruta.read_text(encoding='utf-8-sig')
    arbol=ast.parse(texto)
    objetivos=[n.value for n in arbol.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MIDDLEWARE' for t in n.targets)]
    if len(objetivos)!=1:raise RuntimeError('No se encontró una única lista MIDDLEWARE en config/settings.py.')
    nodo=objetivos[0]
    try:lista=list(ast.literal_eval(nodo))
    except (ValueError,TypeError):raise RuntimeError('MIDDLEWARE debe ser una lista literal para realizar la actualización automática.')
    auth='django.contrib.auth.middleware.AuthenticationMiddleware';seg='seguridad.middleware.PermisosModulosMiddleware'
    if auth not in lista:raise RuntimeError('Falta AuthenticationMiddleware. No se ha modificado la configuración.')
    nueva=[m for m in lista if m!=seg];nueva.insert(nueva.index(auth)+1,seg)
    if nueva==lista:
        print('La protección de módulos ya está instalada.');return False
    lineas=texto.splitlines(keepends=True)
    inicio=sum(len(l) for l in lineas[:nodo.lineno-1])+nodo.col_offset
    fin=sum(len(l) for l in lineas[:nodo.end_lineno-1])+nodo.end_col_offset
    reemplazo='[\n'+''.join('    '+repr(m)+',\n' for m in nueva)+']'
    nuevo=texto[:inicio]+reemplazo+texto[fin:];ast.parse(nuevo)
    respaldo=raiz/('respaldo_seguridad_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    respaldo.mkdir();shutil.copy2(ruta,respaldo/'settings.py')
    ruta.write_text(nuevo,encoding='utf-8')
    print('Protección instalada. Se conservó un respaldo de settings.py. Ejecuta manage.py check y manage.py migrate.')
    return True

if __name__=='__main__':instalar()
