(() => {
  const form = document.getElementById('pago-proveedor');
  const salida = document.getElementById('conversion-proveedor');
  if (!form || !salida) return;
  const datos = JSON.parse(document.getElementById('conversion-proveedor-datos').textContent);
  const catalogo = JSON.parse(document.getElementById('catalogo-proveedor').textContent);
  const fecha = form.elements.namedItem('fecha');
  const montoCampo = form.elements.namedItem('monto');
  const errorAbono = document.getElementById('error-abono');
  let tasaTexto = null;
  const centimos = valor => {
    const texto = String(valor).trim();
    if (!/^\d+(?:\.\d{1,2})?$/.test(texto)) return null;
    const [entero, decimal = ''] = texto.split('.');
    return BigInt(entero) * 100n + BigInt(decimal.padEnd(2, '0'));
  };
  function validarAbono() {
    const tipo = catalogo[form.elements.namedItem('tipo_pago').value];
    const monto = centimos(montoCampo.value);
    const saldo = centimos(datos.saldo);
    const cambio = tasaTexto === null ? null : centimos(tasaTexto);
    let exceso = false;
    if (tipo && monto !== null && saldo !== null) {
      if (tipo.moneda === datos.divisa) exceso = monto > saldo;
      else if (cambio !== null && cambio > 0n) {
        exceso = tipo.moneda === 'USD' ? monto * cambio > saldo * 100n : monto * 100n > saldo * cambio;
      }
    }
    const mensaje = exceso ? 'El abono supera el saldo pendiente de la factura (' + formato(datos.saldo) + ' ' + (datos.divisa === 'BS' ? 'Bs.' : 'USD') + '). Cambia el monto o cancela el pago.' : '';
    montoCampo.setCustomValidity(mensaje);
    if (errorAbono) { errorAbono.hidden = !exceso; errorAbono.textContent = mensaje; }
    return !exceso;
  }
  let tasa = null, turno = 0, peticion;
  const formato = n => Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  function mostrar() {
    validarAbono();
    if (!tasa) return;
    const tipo = catalogo[form.elements.namedItem('tipo_pago').value];
    const monto = Number(form.elements.namedItem('monto').value) || 0;
    const totalBs = datos.divisa === 'BS' ? Number(datos.total) : Number(datos.total) * tasa;
    const saldoBs = datos.divisa === 'BS' ? Number(datos.saldo) : Number(datos.saldo) * tasa;
    salida.className = 'alert alert-success text-end';
    salida.textContent = 'Tasa Bs: ' + formato(tasa) + ' · Total de factura equivalente: ' + formato(totalBs) + ' Bs. · Saldo equivalente: ' + formato(saldoBs) + ' Bs.';
    if (tipo && monto > 0) salida.textContent += ' · Este pago equivale a: ' + formato(tipo.moneda === 'BS' ? monto : monto * tasa) + ' Bs.';
  }
  async function consultar() {
    const actual = ++turno;
    peticion?.abort(); peticion = new AbortController(); tasa = null; tasaTexto = null; validarAbono();
    salida.className = 'alert alert-info text-end'; salida.textContent = 'Consultando tasa Bs…';
    try {
      const url = new URL(form.dataset.tasaUrl, location.origin); url.searchParams.set('fecha', fecha.value);
      const respuesta = await fetch(url, {signal: peticion.signal, headers: {'Accept': 'application/json'}});
      if (respuesta.redirected) throw new Error();
      const cuerpo = await respuesta.json(); if (actual !== turno) return;
      if (!respuesta.ok) { salida.className = 'alert alert-danger text-end'; salida.textContent = cuerpo.error || 'No hay tasa Bs.'; return; }
      tasaTexto = cuerpo.tasa; tasa = Number(cuerpo.tasa); if (!(tasa > 0)) throw new Error(); mostrar();
    } catch (error) {
      if (error.name !== 'AbortError' && actual === turno) { salida.className = 'alert alert-danger text-end'; salida.textContent = 'No se pudo consultar la tasa Bs.'; }
    }
  }
  fecha.addEventListener('change', consultar);
  form.elements.namedItem('tipo_pago').addEventListener('change', mostrar);
  form.elements.namedItem('monto').addEventListener('input', mostrar);
  form.addEventListener('submit', evento => {
    if (!validarAbono()) { evento.preventDefault(); errorAbono?.focus(); }
  });
  montoCampo.addEventListener('invalid', () => { if (errorAbono && !errorAbono.hidden) errorAbono.focus(); });
  document.getElementById('error-abono-servidor')?.focus();
  consultar();
})();
