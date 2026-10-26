(() => {
 const formato = n => Number(n).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2});
 const form=document.getElementById("form-conteo");
 const confirmar=document.getElementById("confirmar-cierre");
 if(!form||!confirmar)return;
 let pendiente=false;
 form.addEventListener("input",e=>{
   if(!e.target.name?.endsWith("-fisico"))return;
   pendiente=true;confirmar.disabled=true;
   document.getElementById("conteo-sin-guardar").hidden=false;
   const fila=e.target.closest("tr"),texto=e.target.value;
   const celda=fila.querySelector(".diferencia-actual");
   if(texto===""){celda.textContent="—";return;}
   const bruto=Number(texto)-Number(fila.dataset.teorico);
   const diferencia=Math.sign(bruto)*Math.round((Math.abs(bruto)+Number.EPSILON)*100)/100;
   celda.textContent=formato(diferencia);
   celda.classList.toggle("text-danger",diferencia!==0);
   celda.classList.toggle("fw-bold",diferencia!==0);
 });
 form.addEventListener("submit",()=>{pendiente=false;});
 confirmar.form.addEventListener("submit",e=>{
   if(pendiente){e.preventDefault();document.getElementById("conteo-sin-guardar").hidden=false;}
 });
 window.addEventListener("beforeunload",e=>{if(pendiente){e.preventDefault();e.returnValue="";}});
})();
