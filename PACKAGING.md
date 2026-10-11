# Empaquetar Free2Play en Windows

## Generar la aplicación portable

Desde PowerShell, en la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build_windows.ps1
```

El resultado es `dist\Free2Play\Free2Play.exe`, acompañado por
`Free2PlayWorker.exe` y los recursos necesarios. Distribuye toda la carpeta
`dist\Free2Play`; no copies únicamente el ejecutable principal.

El ejecutable auxiliar conserva el formato CLI que la interfaz necesita para
leer eventos JSON Lines de TikTok y para recibir la salida del instalador de
API Bridge. La ventana principal no abre una consola adicional.

## Crear un instalador por usuario

Instala Inno Setup y compila `Free2Play.iss` desde Inno Setup o con:

```powershell
iscc .\Free2Play.iss
```

El instalador no requiere permisos de administrador y coloca el programa en
`%LOCALAPPDATA%\Programs\Free2Play`. Los perfiles y reglas se guardan en
`%APPDATA%\Free2Play`; los ajustes y el valor VIP cifrado por DPAPI permanecen
en `%LOCALAPPDATA%\Free2Play`. Desinstalar el programa no elimina esos datos.

En el primer inicio, `rules.json` y `profiles.json` situados junto a la
aplicación se copian a AppData solo si aún no existen allí. Así se conserva
la configuración previa y nunca se sobrescriben datos de usuario.

## Publicar en GitHub

El workflow `.github/workflows/release-windows.yml` ejecuta las pruebas,
construye el paquete y adjunta `Free2Play-Windows.zip` automáticamente cuando
se publica un GitHub Release. Crea y publica un Release en GitHub; espera a que
termine la acción **Build Windows release** para que aparezca el ZIP entre sus
archivos descargables. También puedes adjuntar manualmente la carpeta portable
comprimida o el instalador.

No publiques `rules.json`, `profiles.json`, `settings.json` ni credenciales
personales. El directorio `dist` contiene los artefactos de compilación y no
debe confundirse con los datos persistentes del usuario.
