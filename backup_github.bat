@echo off
setlocal

color 0A
title BarberPro - Respaldo GitHub

::==========================
:: CONFIGURACION
::==========================
set PROYECTO=C:\Users\guerr\Proyectos\Barberia

::==========================
:: FECHA Y HORA
::==========================
echo.
echo ================================================
echo            BARBERPRO - RESPALDO GITHUB
echo ================================================
echo.
echo Fecha: %date%
echo Hora : %time%
echo.

cd /d "%PROYECTO%"

echo Verificando repositorio...
git status

echo.
set /p MENSAJE=Describe los cambios realizados: 

if "%MENSAJE%"=="" (
    set MENSAJE=Actualizacion del proyecto
)

echo.
echo ================================================
echo Agregando archivos...
git add .

echo.
echo Creando commit...
git commit -m "%MENSAJE%"

IF ERRORLEVEL 1 (
    echo.
    echo No hay cambios para guardar o ocurrio un error.
    pause
    exit /b
)

echo.
echo Sincronizando con GitHub...
git pull --rebase

echo.
echo Subiendo respaldo...
git push

echo.
echo ================================================
echo RESPALDO COMPLETADO
echo ================================================
echo.

echo Commit:
echo %MENSAJE%

echo.
pause