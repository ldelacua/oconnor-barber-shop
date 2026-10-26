(() => {
 const aviso=document.getElementById("aviso-existencias");
 if(!aviso)return;
 if(typeof aviso.showModal==="function")aviso.showModal();
 else{aviso.setAttribute("open","");aviso.style.position="fixed";aviso.style.top="20%";aviso.style.zIndex="2000";}
 document.getElementById("corregir-cantidad").addEventListener("click",()=>{
   if(typeof aviso.close==="function")aviso.close();else aviso.removeAttribute("open");
   const producto=[...document.querySelectorAll('#lineas-cuerpo [name$="-producto"]')].find(c=>c.value===aviso.dataset.producto);
   const campo=producto?.closest("tr")?.querySelector('[name$="-cantidad"]')||document.querySelector('#lineas-cuerpo [name$="-cantidad"]');
   campo?.focus?.();campo?.select?.();
 });
})();
