(() => {
 const formato = n => Number(n).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2});
 const form=document.getElementById("ajuste-inventario");if(!form)return;
 async function cargar(fila){
   const producto=fila.querySelector('[name$="-producto"]').value;
   const fecha=form.elements.namedItem("fecha").value;
   const salida=fila.querySelector(".costo-fila");
   const turno=(Number(fila.dataset.turno)||0)+1;fila.dataset.turno=turno;
   if(!producto||!fecha){salida.textContent="SELECCIONA PRODUCTO Y FECHA.";return;}
   salida.textContent="CONSULTANDO…";
   try{
     const url=new URL(form.dataset.costoUrl,location.origin);url.searchParams.set("producto",producto);url.searchParams.set("fecha",fecha);
     const r=await fetch(url,{headers:{"Accept":"application/json"}});if(!r.ok||r.redirected)throw new Error();
     const datos=await r.json();if(Number(fila.dataset.turno)!==turno)return;
     salida.textContent="USD "+formato(datos.costo)+(datos.sin_previo?" · SIN COSTO PREVIO":"");
   }catch(_){if(Number(fila.dataset.turno)===turno)salida.textContent="NO SE PUDO CONSULTAR EL COSTO.";}
 }
 const cuerpo=document.getElementById("ajustes-cuerpo");
 cuerpo.addEventListener("change",e=>{
   const fila=e.target.closest(".ajuste-fila");
   if(fila&&e.target.name?.endsWith("-producto"))cargar(fila);
 });
 form.elements.namedItem("fecha").addEventListener("change",()=>cuerpo.querySelectorAll(".ajuste-fila").forEach(cargar));
 document.getElementById("agregar-ajuste").addEventListener("click",()=>{
   const total=document.getElementById("id_lineas-TOTAL_FORMS"),n=Number(total.value);
   if(n>=100){alert("MÁXIMO 100 PRODUCTOS.");return;}
   cuerpo.insertAdjacentHTML("beforeend",document.getElementById("ajuste-vacio").innerHTML.replaceAll("__prefix__",String(n)));
   total.value=n+1;window.iniciarBuscadoresInventario?.(cuerpo);
 });
 cuerpo.querySelectorAll(".ajuste-fila").forEach(cargar);
})();
