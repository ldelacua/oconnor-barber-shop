(() => {
  document.addEventListener("input", e => {
    if (e.target.matches("[data-mayusculas]")) {
      const campo = e.target, inicio = campo.selectionStart, fin = campo.selectionEnd;
      campo.value = campo.value.toUpperCase();
      if (inicio !== null && typeof campo.setSelectionRange === "function") campo.setSelectionRange(inicio, fin);
    }
  });
  const form = document.getElementById("maestro-form");
  if (!form) return;
  const clave = "inventario-maestro:" + location.pathname + location.search;
  try {
    const datos = JSON.parse(sessionStorage.getItem(clave) || "null");
    sessionStorage.removeItem(clave);
    if (datos) for (const [nombre, valor] of Object.entries(datos)) {
      const campo = form.elements.namedItem(nombre);
      if (!campo || nombre === "csrfmiddlewaretoken" || nombre === "next") continue;
      if (campo.type === "checkbox") campo.checked = valor;
      else campo.value = valor;
    }
  } catch (_) {}
  document.querySelectorAll(".conservar-maestro").forEach(a => a.addEventListener("click", () => {
    const datos = {};
    for (const campo of form.elements) {
      if (campo.name && campo.name !== "csrfmiddlewaretoken") datos[campo.name] = campo.type === "checkbox" ? campo.checked : campo.value;
    }
    try { sessionStorage.setItem(clave, JSON.stringify(datos)); } catch (_) {}
  }));
  form.addEventListener("submit", () => { try { sessionStorage.removeItem(clave); } catch (_) {} });
})();
