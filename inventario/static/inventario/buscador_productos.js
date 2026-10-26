(() => {
 const formato = n => Number(n).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2});
  function iniciar(raiz) {
    raiz.querySelectorAll(".buscador-producto").forEach(contenedor => {
      if (contenedor.dataset.iniciado) return;
      contenedor.dataset.iniciado = "1";
      const input = contenedor.querySelector(".producto-buscar");
      const id = contenedor.querySelector('input[type="hidden"]');
      const lista = contenedor.querySelector(".producto-resultados");
      const ayuda = contenedor.querySelector(".producto-ayuda");
      let temporizador, peticion, secuencia = 0, activo = -1;
      const cerrar = () => {
        lista.hidden = true; input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant"); activo = -1;
      };
      const resaltar = () => {
        [...lista.querySelectorAll("button")].forEach((b,i) => {
          b.classList.toggle("active", i === activo);
          b.setAttribute("aria-selected", String(i === activo));
          if (i === activo) { input.setAttribute("aria-activedescendant", b.id); b.scrollIntoView?.({block:"nearest"}); }
        });
      };
      input.addEventListener("input", () => {
        input.value = input.value.toUpperCase();
        id.value = ""; id.dispatchEvent(new Event("change", {bubbles:true}));
        clearTimeout(temporizador); peticion?.abort(); secuencia++; cerrar();
        const texto = input.value.trim();
        if (!texto) { ayuda.textContent = "ESCRIBE Y SELECCIONA UN RESULTADO."; return; }
        const turno = secuencia;
        temporizador = setTimeout(async () => {
          peticion = new AbortController();
          ayuda.textContent = "BUSCANDO…";
          try {
            const url = new URL(contenedor.dataset.url, location.origin);
            url.searchParams.set("q", texto);
            const r = await fetch(url, {signal:peticion.signal, headers:{"Accept":"application/json"}});
            if (!r.ok || r.redirected) throw new Error("consulta");
            const datos = await r.json();
            if (turno !== secuencia) return;
            lista.replaceChildren();
            datos.resultados.forEach((p, indice) => {
              const boton = document.createElement("button");
              boton.type = "button"; boton.className = "list-group-item list-group-item-action";
              boton.id = input.id + "_opcion_" + indice;
              boton.setAttribute("role", "option");
              boton.textContent = p.texto;
              boton.addEventListener("click", () => {
                id.value = String(p.id); input.value = p.texto;
                ayuda.textContent = p.existencia !== undefined ? "EXISTENCIA: " + formato(Math.floor(Number(p.existencia)*100+1e-8)/100) : "PRODUCTO SELECCIONADO."; cerrar();
                id.dispatchEvent(new Event("change", {bubbles:true}));
              });
              lista.appendChild(boton);
            });
            ayuda.textContent = datos.hay_mas ? "HAY MÁS PRODUCTOS. ESCRIBE MÁS PARA FILTRAR." :
              datos.resultados.length ? "SELECCIONA EL PRODUCTO." : "NO HAY COINCIDENCIAS.";
            const rect = input.getBoundingClientRect();
            lista.style.left = rect.left + "px"; lista.style.right = "auto";
            lista.style.top = rect.bottom + "px"; lista.style.width = rect.width + "px";
            lista.style.maxHeight = Math.max(100, Math.min(260, window.innerHeight - rect.bottom - 12)) + "px";
            lista.hidden = !datos.resultados.length;
            input.setAttribute("aria-expanded", String(!lista.hidden));
          } catch (error) {
            if (error.name !== "AbortError" && turno === secuencia) {
              ayuda.textContent = "NO SE PUDO BUSCAR. INTENTA NUEVAMENTE."; cerrar();
            }
          }
        }, 250);
      });
      input.addEventListener("keydown", e => {
        const botones = [...lista.querySelectorAll("button")];
        if (e.key === "Escape") { cerrar(); return; }
        if (lista.hidden || !botones.length) {
          if (e.key === "Enter" && !id.value) {
            e.preventDefault(); ayuda.textContent = "ESCRIBE Y SELECCIONA UN RESULTADO.";
          }
          return;
        }
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          activo = (activo + (e.key === "ArrowDown" ? 1 : -1) + botones.length) % botones.length; resaltar();
        } else if (e.key === "Enter") {
          e.preventDefault(); botones[activo >= 0 ? activo : 0].click();
        }
      });
      input.addEventListener("blur", () => setTimeout(cerrar, 180));
      window.addEventListener("resize", cerrar);
      window.addEventListener("scroll", e => { if (!lista.contains(e.target)) cerrar(); }, true);
    });
  }
  window.iniciarBuscadoresInventario = iniciar;
  iniciar(document);
})();
