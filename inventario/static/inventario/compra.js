(() => {
 const formato = n => Number(n).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2});
  const form = document.getElementById("compra-form");
  if (!form) return;
  const cuerpo = document.getElementById("detalle-cuerpo");
  const total = document.getElementById("id_detalles-TOTAL_FORMS");
  const fecha = form.elements.namedItem("fecha_compra");
  const clave = "inventario-editor:" + location.pathname;
  const ivaInicial = JSON.parse(document.getElementById("iva-inventario").textContent);
  let iva = ivaInicial === null ? null : Number(ivaInicial);
  let secuencia = 0, peticion;
  const agregar = () => {
    const n = Number(total.value);
    if (n >= 100) { alert("MÁXIMO 100 PRODUCTOS POR COMPRA."); return; }
    const html = document.getElementById("fila-vacia").innerHTML.replaceAll("__prefix__", String(n));
    cuerpo.insertAdjacentHTML("beforeend", html);
    total.value = n + 1;
    window.iniciarBuscadoresInventario?.(cuerpo);
  };
  document.getElementById("agregar-fila").addEventListener("click", () => { agregar(); calcular(); });
  function calcular() {
    const salida = document.getElementById("total-compra");
    if (iva === null || !Number.isFinite(iva)) { salida.textContent = "Total: —"; return; }
    let suma = 0;
    const divisa = form.elements.namedItem("divisa").value === "USD" ? "USD" : "Bs";
    cuerpo.querySelectorAll(".detalle-fila").forEach(fila => {
      const num = nombre => Number(fila.querySelector('[name$="-' + nombre + '"]').value) || 0;
      const borrar = fila.querySelector('[name$="-DELETE"]').checked;
      const base = Math.round((num("cantidad") * num("precio_unitario") + Number.EPSILON) * 100) / 100;
      const impuesto = Math.round((base * iva / 100 + Number.EPSILON) * 100) / 100;
      const importe = base + impuesto;
      fila.style.opacity = borrar ? ".45" : "1";
      fila.querySelector(".importe-fila").textContent = borrar ? "SE QUITARÁ" : formato(importe) + " " + divisa;
      if (!borrar) suma += importe;
    });
    salida.textContent = "Total: " + formato(suma) + " " + divisa;
  }
  async function cargarCondiciones() {
    const turno = ++secuencia;
    peticion?.abort();
    peticion = new AbortController();
    const info = document.getElementById("tasa-bcv");
    info.textContent = "CONSULTANDO TASA BCV…";
    try {
      const url = new URL(form.dataset.condicionesUrl, location.origin);
      url.searchParams.set("fecha", fecha.value);
      const r = await fetch(url, {signal: peticion.signal, headers: {"Accept":"application/json"}});
      if (r.redirected) throw new Error("sesion");
      const datos = await r.json();
      if (turno !== secuencia) return;
      if (!r.ok) { info.textContent = datos.error || "NO HAY TASA PARA ESTA FECHA."; return; }
      iva = Number(datos.iva);
      info.textContent = formato(datos.tasa);
      calcular();
    } catch (error) {
      if (error.name !== "AbortError" && turno === secuencia) info.textContent = "NO SE PUDO CONSULTAR LA TASA. INTENTA NUEVAMENTE.";
    }
  }
  fecha.addEventListener("change", cargarCondiciones);
  let restaurado = false;
  try {
    const guardado = sessionStorage.getItem(clave);
    if (guardado) {
      sessionStorage.removeItem(clave);
      const datos = JSON.parse(guardado);
      while (Number(total.value) < Math.min(datos.filas || 0, 100)) agregar();
      for (const [nombre, valor] of Object.entries(datos.campos || {})) {
        const campo = form.elements.namedItem(nombre);
        if (!campo || nombre === "csrfmiddlewaretoken" || nombre.endsWith("-id") || nombre === "next") continue;
        if (campo.type === "checkbox") campo.checked = valor;
        else if (campo.tagName === "SELECT") {
          if ([...campo.options].some(o => o.value === valor)) campo.value = valor;
        } else campo.value = valor;
      }
      restaurado = true;
    }
  } catch (_) {}
  document.querySelectorAll(".salir-editor").forEach(enlace => enlace.addEventListener("click", () => {
    const campos = {};
    for (const campo of form.elements) {
      if (!campo.name || campo.name === "csrfmiddlewaretoken") continue;
      campos[campo.name] = campo.type === "checkbox" ? campo.checked : campo.value;
    }
    try { sessionStorage.setItem(clave, JSON.stringify({filas:Number(total.value), campos})); } catch (_) {}
  }));
  form.addEventListener("submit", () => {
    try { sessionStorage.removeItem(clave); } catch (_) {}
  });
  form.addEventListener("input", calcular);
  form.addEventListener("change", calcular);
  if (restaurado) cargarCondiciones();
  calcular();
})();
