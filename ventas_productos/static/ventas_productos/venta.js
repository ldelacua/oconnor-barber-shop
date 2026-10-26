(() => {
 const formato = n => Number(n).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2});
 const form=document.getElementById("venta-productos");if(!form)return;
 let tasa=null,iva=null,escalas=[],secuencia=0,peticion;
 const catalogo=JSON.parse(document.getElementById("catalogo-pagos-productos").textContent);
 const redondear=n=>Math.round((n+Number.EPSILON)*100)/100;
 const clave="venta-productos:"+location.pathname;
 const num=(fila,campo)=>Number(fila.querySelector('[name$="-'+campo+'"]').value)||0;
 const borrada=fila=>fila.querySelector('[name$="-DELETE"]').checked;
 const todas=()=>[...document.querySelectorAll("#lineas-cuerpo .linea-producto")];
 function calcular(){
   const salida=document.getElementById("total-venta"),resumen=document.getElementById("resumen-factura");
   resumen.replaceChildren();
   const filas=todas().filter(f=>!borrada(f)&&f.querySelector('[name$="-producto"]').value);
   if(!tasa||iva===null||filas.some(f=>!f.dataset.precio||num(f,"cantidad")<=0)){
     salida.textContent="Total general: —";document.getElementById("saldo-pagos").textContent="";return;
   }
   const unidades=redondear(filas.reduce((s,f)=>s+num(f,"cantidad"),0));
   const tramo=escalas.filter(r=>unidades>=Number(r.unidades)).sort((a,b)=>Number(b.unidades)-Number(a.unidades))[0];
   const descuento=tramo?Number(tramo.porcentaje):0;
   let bruto=0,rebajas=0,impuestos=0;
   todas().forEach(fila=>{
      fila.style.opacity=borrada(fila)?".4":"1";
      const seleccion=fila.querySelector('[name$="-producto"]').value;
      if(borrada(fila)||!seleccion){fila.querySelector(".importe-linea").textContent=borrada(fila)?"SE QUITARÁ":"—";return;}
      const usd=redondear(num(fila,"cantidad")*Number(fila.dataset.precio));
      const rebajaUSD=redondear(usd*descuento/100),bs=redondear(usd*tasa);
      const netoBS=redondear((usd-rebajaUSD)*tasa),impuesto=redondear(netoBS*iva/100);
      bruto+=bs;rebajas+=bs-netoBS;impuestos+=impuesto;
      fila.querySelector(".importe-linea").textContent=formato(redondear((netoBS+impuesto)/tasa));
   });
   bruto=redondear(bruto);rebajas=redondear(rebajas);impuestos=redondear(impuestos);
   const base=redondear(bruto-rebajas),totalBS=redondear(base+impuestos),totalUSD=redondear(totalBS/tasa);
   const parrafo=t=>{const p=document.createElement("p");p.className="mb-1";p.textContent=t;resumen.appendChild(p);};
   parrafo("Unidades de la factura: "+formato(unidades));
   parrafo("Subtotal: Bs "+formato(bruto));
   if(descuento)parrafo("Descuento "+formato(descuento)+" %: Bs "+formato(rebajas));
   parrafo("Base imponible: Bs "+formato(base));
   parrafo("IVA "+formato(iva)+" %: Bs "+formato(impuestos));
   salida.textContent="Total general: USD "+formato(totalUSD)+" · Bs "+formato(totalBS);
   let usd=0,bs=0,soloUSD=true,contar=0;
   document.querySelectorAll("#pagos-cuerpo .pago-producto").forEach(fila=>{
      const tipo=catalogo[fila.querySelector('[name$="-tipo_pago"]').value];
      fila.style.opacity=borrada(fila)?".4":"1";
      if(borrada(fila)||!tipo)return;
      contar++;
      if(tipo.moneda==="USD")usd+=num(fila,"monto");else{bs+=num(fila,"monto");soloUSD=false;}
   });
   const diferencia=redondear(soloUSD?totalUSD-usd:totalBS-redondear(usd*tasa)-bs);
   document.getElementById("saldo-pagos").textContent=totalBS===0?
      (contar?"TOTAL CERO: QUITA LOS PAGOS.":"TOTAL CERO: NO REQUIERE PAGOS."):
      !contar?"REGISTRA LOS PAGOS.":diferencia===0?"PAGOS COMPLETOS.":
      (diferencia>0?"FALTAN ":"SOBRAN ")+formato(Math.abs(diferencia))+(soloUSD?" USD":" Bs");
 }
 async function cargarPrecio(fila){
   const producto=fila.querySelector('[name$="-producto"]').value;
   const fecha=form.elements.namedItem("fecha").value;
   const campo=fila.querySelector(".precio-automatico"),ayuda=fila.querySelector(".precio-ayuda");
   const turno=(Number(fila.dataset.versionPrecio)||0)+1;fila.dataset.versionPrecio=turno;
   fila.dataset.precio="";ayuda.textContent="";
   if(!producto||!fecha){campo.value="—";calcular();return;}
   campo.value="CONSULTANDO…";calcular();
   try{
     const url=new URL(form.dataset.precioUrl,location.origin);url.searchParams.set("producto",producto);url.searchParams.set("fecha",fecha);
     const r=await fetch(url,{headers:{"Accept":"application/json"}});if(r.redirected)throw new Error();
     const datos=await r.json();if(Number(fila.dataset.versionPrecio)!==turno)return;
     if(!r.ok){campo.value="SIN PRECIO";ayuda.textContent=datos.error||"CONFIGURA EL PORCENTAJE.";return;}
     fila.dataset.precio=datos.precio_unitario_usd;campo.value=formato(datos.precio_unitario_usd);
     ayuda.textContent="COSTO USD "+formato(datos.costo_unitario_usd)+" + "+formato(datos.porcentaje_venta)+" %";
     calcular();
   }catch(_){if(Number(fila.dataset.versionPrecio)===turno){campo.value="SIN PRECIO";ayuda.textContent="NO SE PUDO CALCULAR EL PRECIO.";}}
 }
 async function cotizar(){
   const turno=++secuencia;peticion?.abort();peticion=new AbortController();
   const salida=document.getElementById("bcv-venta");salida.textContent="CONSULTANDO…";tasa=null;calcular();
   try{
      const url=new URL(form.dataset.condicionesUrl,location.origin);url.searchParams.set("fecha",form.elements.namedItem("fecha").value);
      const r=await fetch(url,{signal:peticion.signal,headers:{"Accept":"application/json"}});
      if(r.redirected)throw new Error();
      const datos=await r.json();if(turno!==secuencia)return;
      if(!r.ok){salida.textContent=datos.error;return;}
      tasa=Number(datos.tasa);iva=Number(datos.iva);escalas=datos.escalas||[];
      salida.textContent=formato(tasa);
      todas().forEach(cargarPrecio);calcular();
   }catch(e){if(e.name!=="AbortError"&&turno===secuencia)salida.textContent="NO SE PUDO CONSULTAR LA TASA BCV.";}
 }
 function agregar(tipo){
    const lineas=tipo==="lineas",total=document.getElementById("id_"+tipo+"-TOTAL_FORMS"),n=Number(total.value);
    if(n>=(lineas?50:20)){alert("SE ALCANZÓ EL MÁXIMO DE RENGLONES.");return;}
    const plantilla=document.getElementById(lineas?"linea-vacia":"pago-vacio"),cuerpo=document.getElementById(tipo+"-cuerpo");
    cuerpo.insertAdjacentHTML("beforeend",plantilla.innerHTML.replaceAll("__prefix__",String(n)));total.value=n+1;
    if(lineas)window.iniciarBuscadoresInventario?.(cuerpo);
 }
 document.getElementById("agregar-producto").addEventListener("click",()=>{agregar("lineas");calcular();});
 document.getElementById("agregar-pago").addEventListener("click",()=>{agregar("pagos");calcular();});
 try{
    const anterior=JSON.parse(sessionStorage.getItem(clave)||"null");sessionStorage.removeItem(clave);
    if(anterior){
      for(const tipo of ["lineas","pagos"]){const total=document.getElementById("id_"+tipo+"-TOTAL_FORMS");while(Number(total.value)<Math.min(anterior[tipo]||0,tipo==="lineas"?50:20))agregar(tipo);}
      for(const [nombre,valor] of Object.entries(anterior.campos||{})){
        if(nombre==="csrfmiddlewaretoken")continue;
        const campo=nombre.startsWith("#")?document.getElementById(nombre.slice(1)):form.elements.namedItem(nombre);
        if(!campo||!form.contains(campo))continue;
        if(campo.type==="checkbox")campo.checked=valor;else campo.value=valor;
      }
    }
 }catch(_){}
 document.querySelectorAll(".salir-venta").forEach(a=>a.addEventListener("click",()=>{
    const campos={};for(const c of form.elements){const nombre=c.name||(c.id?"#"+c.id:"");if(nombre&&nombre!=="csrfmiddlewaretoken")campos[nombre]=c.type==="checkbox"?c.checked:c.value;}
    try{sessionStorage.setItem(clave,JSON.stringify({campos,lineas:Number(document.getElementById("id_lineas-TOTAL_FORMS").value),pagos:Number(document.getElementById("id_pagos-TOTAL_FORMS").value)}));}catch(_){}
 }));
 form.addEventListener("submit",()=>{try{sessionStorage.removeItem(clave);}catch(_){}});
 form.addEventListener("input",calcular);form.addEventListener("change",calcular);
 document.getElementById("lineas-cuerpo").addEventListener("change",e=>{if(e.target.name?.endsWith("-producto"))cargarPrecio(e.target.closest("tr"));});
 form.elements.namedItem("fecha").addEventListener("change",cotizar);
 cotizar();
})();
