# Free2Play

Free2Play conecta eventos de un LIVE de TikTok con una instancia local de
Minecraft mediante API Bridge. La interfaz y los mensajes están en español.

> **Importante:** usa primero un mundo de prueba. Las reglas pueden invocar
> entidades hostiles, TNT, rayos y teletransportar jugadores. Una prueba HTTP
> confirma que API Bridge recibió la petición; no garantiza que el comando se
> haya completado dentro del juego.

## Descargar y abrir en Windows

1. Descarga `Free2Play-Windows.zip` desde la sección **Releases** de este
   repositorio.
2. Extrae el ZIP completo en una carpeta que puedas escribir, por ejemplo
   `Descargas\Free2Play`. No ejecutes el programa dentro del ZIP.
3. Abre la carpeta `Free2Play` extraída y ejecuta `Free2Play.exe`.
4. Si Windows muestra una confirmación de seguridad, verifica que descargaste
   el archivo desde el Release oficial del proyecto antes de permitir su
   ejecución.

El paquete portable no requiere instalar Python. Conserva también
`Free2PlayWorker.exe` y la carpeta `_internal`: la aplicación los necesita.
El instalador opcional se instala por usuario en
`%LOCALAPPDATA%\Programs\Free2Play` y no requiere permisos de administrador.

## Primer uso: conectar Minecraft

Conecta y prueba Minecraft **antes** de activar TikTok o la automatización.

### 1. Prepara una instancia compatible

1. Usa una instalación de Minecraft Java con un mod loader compatible con la
   versión elegida. API Bridge se distribuye para versiones y loaders
   específicos; no todas las combinaciones existen.
2. En Free2Play abre **Minecraft**.
3. En **Carpeta de instancia**, pulsa **Seleccionar…** y elige la carpeta raíz
   de la instancia que vas a iniciar. Debe ser la misma instancia donde están
   `mods` y `logs`. En launchers con varias instancias no elijas otra carpeta
   aunque también se llame `.minecraft`.
4. Escribe la versión exacta del juego, por ejemplo `1.21.11`, y selecciona
   el loader correspondiente. La versión debe coincidir con la instancia.
5. Pulsa **Descargar API Bridge en mods** y espera a que el estado indique que
   la descarga se verificó. El instalador descarga únicamente el JAR de API
   Bridge; no instala el loader ni otras dependencias del mod.
6. Inicia esa instancia de Minecraft. Entra a un mundo o servidor donde puedas
   ejecutar comandos y donde esté permitido usar mods. Mantén el juego abierto.

### 2. Obtén el token de esa instancia y comprueba API Bridge

1. En Free2Play, revisa que la carpeta de instancia seleccionada sea la misma
   que acabas de iniciar.
2. Pulsa **Obtener token del log**. La aplicación busca el token generado por
   API Bridge en `logs\latest.log` de esa instancia. El token se mantiene en
   memoria y no se muestra en pantalla ni en el registro de actividad.
3. Deja la dirección API predeterminada
   `http://127.0.0.1:25566`, salvo que hayas configurado otro puerto local en
   API Bridge.
4. Pulsa **Conectar Minecraft** o **Probar conexión**. La prueba hace una
   consulta HTTP local a `GET /api/` con el encabezado Bearer. Un estado
   satisfactorio confirma la conexión HTTP con el mod.

El token es una credencial: no lo compartas ni pegues en capturas, incidencias
o mensajes. Free2Play limita estas solicitudes a direcciones locales y no
envía el token a Internet.

### 3. Comprueba un comando con cuidado

1. En **Jugador/selector objetivo**, deja `@a` o indica un jugador Minecraft
   conectado. Este campo se refiere a Minecraft, no al nombre de TikTok.
2. Antes de activar reglas, crea o usa un perfil de prueba con una acción
   sencilla y no destructiva, como enviar un mensaje al chat.
3. Revisa **Registro** y activa **Depuración HTTP** solo si necesitas ver el
   comando y la respuesta del API. La opción no debe mostrar el token.

La respuesta del API puede indicar que el comando fue **encolado**. No es un
acuse de que Minecraft terminó de ejecutarlo. Confirma el resultado en el chat
del juego y en la salida del mod.

## Conectar TikTok LIVE

1. Inicia una transmisión LIVE desde la cuenta que quieras escuchar.
2. En Free2Play abre **TikTok LIVE**.
3. Escribe el identificador público de la cuenta, con o sin `@`, y pulsa
   **Conectar**.
4. Espera a que el estado cambie a conectado. Si no conecta, revisa el mensaje
   de error en **Registro**, confirma que el LIVE está activo y vuelve a
   intentarlo manualmente.
5. Si quieres que Free2Play lo intente al abrir, deja activada la opción
   **Intentar conectar al iniciar la aplicación**. Si el LIVE no está activo,
   aparecerá un error y tendrás que reconectar cuando lo esté.

Cuando la conexión tenga éxito, el catálogo de regalos se podrá seleccionar en
las reglas. Si TikTok no entrega el catálogo, puedes escribir el nombre del
regalo manualmente.

## Crear reglas y activar la automatización

1. Conecta Minecraft y TikTok LIVE siguiendo los pasos anteriores.
2. Abre **Reglas** y selecciona un perfil. El perfil `dani` incluye ejemplos
   de acciones para follows, regalos y likes; puede modificar mucho el mundo.
3. Pulsa **Crear**. Pon un nombre reconocible y selecciona qué evento de TikTok
   debe activar la regla.
4. Opcionalmente añade un filtro:
   - Para regalos, elige un nombre del catálogo o escríbelo. El campo típico es
     `gift_name`.
   - Para comentarios, el campo `text` filtra por texto.
   - Deja filtro y valor vacíos para aceptar todos los eventos de ese tipo.
5. Para comenzar, elige **Por bloques (sencillo)** y selecciona **Enviar
   mensaje al chat** o **Invocar mobs**. Para likes puedes fijar el umbral
   “cada X likes”.
6. Usa **Avanzado (comando)** solo si necesitas escribir comandos Minecraft.
   Escríbelos sin `/`; para ejecutar varios, pon uno por línea.
7. Revisa las variables de la pantalla. Algunos ejemplos son:
   - `{username}`: nombre visible del usuario de TikTok.
   - `{shortname}`: identificador corto de TikTok.
   - `{userid}`: identificador del usuario en TikTok.
   - `{text}`: texto del comentario.
   - `{gift}` o `{gift_name}`: nombre del regalo.
   - `{amount}`: cantidad recibida.
   - `{player}`: objetivo Minecraft configurado en la página Minecraft.
8. Guarda la regla. Selecciónala y usa **Probar coincidencia** para comprobar
   el filtro con un evento de muestra; esta acción no ejecuta el comando.
9. Activa solo las reglas que realmente quieras utilizar y, al final, vuelve a
   **Inicio** y pulsa **Iniciar automatización**. Acepta la confirmación del
   perfil `dani` únicamente en un mundo preparado para ello.

La regla de respaldo para regalos sin coincidencia viene desactivada por
defecto. Si la activas, comprueba primero el comando configurado. Los
comentarios tienen una opción independiente para reenviar el nombre y el texto
al chat de Minecraft.

## Registro, depuración y problemas frecuentes

- **Minecraft no conecta:** confirma que el juego está abierto, API Bridge
  aparece en el log de esa instancia y la carpeta seleccionada corresponde a
  la ejecución actual.
- **No se encuentra el token:** inicia Minecraft después de instalar API
  Bridge y vuelve a pulsar **Obtener token del log**. Si usas un launcher con
  varias instancias, selecciona la carpeta exacta de la instancia.
- **HTTP 401 o 403:** el token no corresponde al mod activo, o se está leyendo
  el `latest.log` de otra instancia. Selecciona la correcta y vuelve a leerlo.
- **Conexión rechazada:** verifica que el mod inició y que la dirección y el
  puerto coinciden con la configuración local de API Bridge.
- **La petición responde, pero no ves el comando:** revisa el resultado HTTP,
  los permisos para comandos, el selector de jugador y el registro del mod.
  La respuesta de recepción solo informa que la petición se aceptó o encoló.
- **TikTok no conecta:** asegúrate de que la transmisión LIVE está activa,
  confirma el usuario y consulta el error en **Registro**. Puedes desconectar
  o volver a intentarlo desde la aplicación.
- **Un comando afecta al mundo de forma inesperada:** pausa la automatización
  desde **Inicio** y prueba en un mundo separado. Las reglas avanzadas se
  ejecutan con los permisos que expone el mod.
- **Necesitas más detalle:** activa el monitor en **Configuración**. Activa
  **Depuración HTTP** temporalmente para registrar comandos/respuestas; nunca
  copies ni publiques tokens.

La ubicación de perfiles y reglas es `%APPDATA%\Free2Play`. Los ajustes se
guardan en `%LOCALAPPDATA%\Free2Play`; el valor VIP se protege con Windows
DPAPI. Estos datos quedan fuera de la carpeta del programa, así que actualizar
o reinstalar no debería reemplazarlos.

## Ejecutar desde el código fuente

Requiere Windows y Python 3.11 o posterior. Desde PowerShell en la carpeta del
proyecto:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Para ejecutar las pruebas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Para compilar el paquete portable, consulta [PACKAGING.md](./PACKAGING.md).

## Seguridad y distribución

Los archivos de perfiles, reglas y ajustes son locales. No subas tus datos
personales, tokens ni archivos de configuración a incidencias o Releases.
Descarga el paquete únicamente desde un Release que controles o en el que
confíes.

El código fuente se publica sin una licencia de código abierto asignada por
ahora. Consulta al mantenedor antes de reutilizar o redistribuir el código.
