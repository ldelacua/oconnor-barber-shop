"""Configuración LOCAL de prueba; solicita la clave sin mostrarla."""
import getpass
import json
import os
import re
from pathlib import Path
import pymysql
pymysql.install_as_MySQLdb()


def main():
    raiz=Path(__file__).resolve().parent
    archivo=raiz/'mysql.local.json'
    if archivo.exists():
        print('Ya existe mysql.local.json. No se reemplazó. Usa manage_mysql.py para continuar.');return
    try:import MySQLdb
    except ImportError:
        raise SystemExit('Primero instala el controlador: python -m pip install -r requirements_mysql.txt')
    base=input('Base de datos [barberia]: ').strip() or 'barberia'
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',base):raise SystemExit('Nombre de base inválido.')
    host=input('Servidor local [127.0.0.1]: ').strip() or '127.0.0.1'
    if host not in {'127.0.0.1','localhost'}:raise SystemExit('Este asistente es para MySQL local. El hosting se configura por separado.')
    puerto=input('Puerto [3306]: ').strip() or '3306'
    if not puerto.isdigit() or not 1<=int(puerto)<=65535:raise SystemExit('Puerto inválido.')
    usuario=input('Usuario MySQL local [root]: ').strip() or 'root'
    clave=getpass.getpass('Contraseña MySQL (no se muestra): ')
    if not clave:raise SystemExit('Introduce la contraseña configurada en MySQL.')
    try:
        con=MySQLdb.connect(host=host,port=int(puerto),user=usuario,passwd=clave,db=base,charset='utf8mb4',connect_timeout=10)
        with con.cursor() as c:
            c.execute('SELECT VERSION()');version=c.fetchone()[0]
            if not version.startswith('8.4.') or 'MariaDB' in version:raise SystemExit('Se requiere MySQL Community Server 8.4 LTS.')
            c.execute('SHOW FULL TABLES');tablas=c.fetchall()
            if tablas:raise SystemExit('La base no está vacía. No se modificó: usa una base nueva para esta inicialización.')
        con.close()
    except MySQLdb.Error as error:
        raise SystemExit(f'No se pudo verificar MySQL (código {error.args[0]}). Revisa conexión, usuario, clave y base. No se guardó la contraseña.')
    datos={'database':base,'host':host,'port':puerto,'user':usuario,'password':clave}
    fd=os.open(str(archivo),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(datos,f,ensure_ascii=False,indent=2)
    ignorar=raiz/'.gitignore'
    texto=ignorar.read_text(encoding='utf-8') if ignorar.exists() else ''
    if not {'mysql.local.json','/mysql.local.json'}.intersection(texto.splitlines()):
        ignorar.write_text(texto.rstrip()+'\n# Credenciales locales de MySQL\n/mysql.local.json\n',encoding='utf-8')
    print('Conexión 8.4 verificada. Configuración local guardada sin mostrar la contraseña.')
    print('Continúa con: python manage_mysql.py migrate')
    print('No se copiaron ni borraron datos de SQLite.')

if __name__=='__main__':main()
