from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin
from .accesos import reglas, permitido


class PermisosModulosMiddleware(MiddlewareMixin):
    def process_view(self,request,view_func,view_args,view_kwargs):
        match=request.resolver_match
        if not match or reglas(match.view_name,request.method,view_kwargs) is None:return None
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(),reverse('iniciar_sesion'))
        if permitido(request.user,match.view_name,request.method,view_kwargs):return None
        mensaje='No tienes permiso para acceder a esta opción o realizar esta operación. Solicita el acceso al administrador.'
        if 'application/json' in request.headers.get('Accept',''):
            return JsonResponse({'error':mensaje},status=403)
        return render(request,'seguridad/sin_permiso.html',{'mensaje':mensaje},status=403)
