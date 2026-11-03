document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-sidebar a').forEach((enlace) => {
    if (enlace.textContent.trim().toLowerCase() === 'dashboard') {
      const opcion = enlace.closest('li.nav-item');
      if (opcion) opcion.hidden = true;
      else enlace.hidden = true;
    }
  });
});
