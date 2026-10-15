@echo off
REM Construye Fontiador.exe (aplicación de ventana, sin consola).
REM Ejecutar en la carpeta AF_FONT, con Python instalado.
py -m pip install --upgrade pyinstaller fonttools shapely pywebview potracer numpy pillow
py -m PyInstaller --onefile --noconsole --name Fontiador --collect-all shapely --collect-all fontTools --collect-all webview --collect-all potrace fontiador_server.py
echo.
echo Listo. Copia dist\Fontiador.exe a la carpeta AF_FONT y ejecútalo desde ahí.
echo El registro de errores queda en fontiador.log junto al ejecutable.
pause
