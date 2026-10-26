"""Conversión controlada de las reglas vigentes a MySQL 8.4.

Solo acepta la gramática de los disparadores incluidos en este proyecto.
No ejecuta SQL proporcionado por usuarios ni modifica el historial SQLite.
"""
import re

IDENT=r'[A-Za-z_][A-Za-z_0-9]*'
REF=rf'{IDENT}\.{IDENT}'
TEXTOS={'tipo_documento','motivo_reverso','registrado_por','nombre_prestador','descripcion_barbero','codigo_servicio','descripcion_servicio','nombre_tipo_pago','moneda','referencia','observacion','tipo','descripcion','codigo','estado','cerrado_por','iniciado_por','descripcion_cliente'}

def exacta(a,b,op):
    if a.lstrip('-').split('.')[-1] in TEXTOS or b.lstrip('-').split('.')[-1] in TEXTOS:
        return f'(CAST({a} AS BINARY) {op} CAST({b} AS BINARY))'
    return f'({a} {op} {b})'

MENSAJE=r"'(?:[^']|'')*'"


def expresiones(sql):
    sql=re.sub(r"date\((\w+\.periodo),'\+1 month','-1 day'\)",r'LAST_DAY(\1)',sql,flags=re.I)
    sql=re.sub(r"date\((\(SELECT MAX\(periodo\) FROM control_inventario_cierremensual WHERE estado='C'\)),'\+1 month'\)",r'DATE_ADD(\1, INTERVAL 1 MONTH)',sql,flags=re.I)
    sql=sql.replace("strftime('%d',NEW.periodo)<>'01'",'DAY(NEW.periodo)<>1')
    sql=re.sub(rf'({REF})\s+IS\s+NOT\s+(-?{REF})',lambda x:'(NOT '+exacta(x[1],x[2],'<=>')+')',sql,flags=re.I)
    sql=re.sub(rf'({REF})\s+IS\s+(-?{REF})',lambda x:exacta(x[1],x[2],'<=>'),sql,flags=re.I)
    # Las comparaciones de las descripciones de reversos deben ser exactas,
    # aunque las búsquedas del usuario utilicen una colación sin distinción de caso.
    def texto_igual(x):
        a,op,b=x.groups()
        if a.lstrip('-').split('.')[-1] in TEXTOS or b.lstrip('-').split('.')[-1] in TEXTOS:
            return exacta(a,b,op)
        return x.group()
    sql=re.sub(rf'({REF})\s*(=|<>)\s*(-?{REF})(?![A-Za-z_0-9])',texto_igual,sql)
    return sql


def signal(mensaje):
    # Django reconoce 3819 como IntegrityError (violación de integridad).
    return "SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT="+mensaje+';'


def convertir(sql):
    patron=rf'^CREATE TRIGGER\s+({IDENT})\s+(BEFORE|AFTER)\s+(INSERT|UPDATE|DELETE)(?:\s+OF\s+{IDENT})?\s+ON\s+({IDENT})\s*(?:WHEN\s+(.*?))?\s*BEGIN\s*(.*?)\s*END\s*$'
    m=re.match(patron,sql.strip(),flags=re.S|re.I)
    if not m:raise ValueError('Definición de disparador no reconocida: '+sql[:100])
    nombre,tiempo,evento,tabla,cuando,cuerpo=m.groups()
    cantidad_antes=len(re.findall(r'RAISE\(ABORT',sql,re.I))
    caso=rf'SELECT\s+CASE\s+WHEN\s+(.*?)\s+THEN\s+RAISE\(ABORT,\s*({MENSAJE})\)\s+END\s*;'
    cuerpo=re.sub(caso,lambda x:'IF ('+expresiones(x[1])+') THEN\n '+signal(x[2])+'\nEND IF;',cuerpo,flags=re.S|re.I)
    cuerpo=re.sub(rf'SELECT\s+RAISE\(ABORT,\s*({MENSAJE})\)\s*;',lambda x:signal(x[1]),cuerpo,flags=re.I)
    cuerpo=expresiones(cuerpo)
    if cuando:cuerpo='IF ('+expresiones(cuando)+') THEN\n'+cuerpo+'\nEND IF;'
    bloqueo="""DECLARE candado_id SMALLINT DEFAULT NULL;
 SELECT id INTO candado_id FROM mysql_candado_operaciones WHERE id=1 FOR UPDATE;
 IF candado_id IS NULL THEN SIGNAL SQLSTATE '23000' SET MYSQL_ERRNO=3819, MESSAGE_TEXT='Falta inicializar el candado MySQL'; END IF;
"""
    resultado=f'CREATE TRIGGER `{nombre}` {tiempo} {evento} ON `{tabla}` FOR EACH ROW\nBEGIN\n'+bloqueo+cuerpo+'\nEND'
    if re.search(r'RAISE\(|strftime\(|\bdate\(|\bUPDATE OF\b|\|\|',resultado,re.I):
        raise ValueError('Quedó SQL exclusivo de SQLite en '+nombre)
    if resultado.count("MYSQL_ERRNO=3819")!=cantidad_antes+1:
        raise ValueError('No se conservaron todas las reglas de '+nombre)
    return nombre,resultado


def convertir_vista(sql):
    sql=sql.replace('CREATE VIEW ci_movimientos AS','CREATE OR REPLACE SQL SECURITY INVOKER VIEW ci_movimientos AS')
    for prefijo,alias in [('C-','m'),('V-','l'),('A-','d')]:
        sql=sql.replace("'"+prefijo+"'||"+alias+'.id',"CONCAT('"+prefijo+"',"+alias+'.id)')
    if '||' in sql:raise ValueError('Concatenación de vista no convertida.')
    return sql
