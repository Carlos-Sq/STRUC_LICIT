# SEACE Monitor — Aviso automático de licitaciones de mochilas/textil

Este programa revisa periódicamente el **Buscador de Contrataciones Menores del SEACE**
(https://prod6.seace.gob.pe/buscador-publico/contrataciones), busca palabras
relacionadas a **mochilas, buzos, polos, textil, uniformes, etc.**, y te avisa
por **Telegram** y **Correo** apenas aparece algo nuevo.

✅ **Siempre** se aseguran marcados los filtros **Objeto = Bien**,
**Objeto = Servicio** y **Estado = Vigente** antes de cada búsqueda (así lo
pediste), para que sólo te avise de bienes y servicios que realmente puedas
ofertar ahora mismo.

---

## ⚠️ Antes de empezar — por qué necesitas ajustar el código

El SEACE es una aplicación web moderna (Angular) que carga los resultados con
JavaScript, no con HTML simple. Por eso el script usa Selenium para controlar
un Chrome real, igual que cuando tú entras a la página.

**No pude "grabar" en vivo los nombres exactos de los campos** (el buscador,
el botón, las columnas de la tabla) porque esa parte del sitio requiere
ejecutar JavaScript, y desde aquí no tengo un navegador conectado al SEACE.
Dejé selectores razonables marcados con `# AJUSTAR` en `seace_monitor.py`,
pero **debes confirmarlos una vez** siguiendo estos 5 pasos (toma ~5 minutos):

1. Abre https://prod6.seace.gob.pe/buscador-publico/contrataciones en Chrome.
2. Presiona `F12` para abrir las Herramientas de Desarrollador.
3. Haz clic derecho sobre el **campo de búsqueda** → "Inspeccionar". Verás algo
   como `<input id="..." placeholder="...">`. Copia ese `id` o `placeholder`.
4. Escribe una palabra (ej. "mochila") y busca. Cuando salgan resultados, haz
   clic derecho sobre una **fila de la tabla** → "Inspeccionar". Fíjate si es
   una `<table>` normal o un componente como `p-datatable` (PrimeNG, muy común
   en el Estado peruano).
5. Abre `seace_monitor.py`, busca las líneas marcadas `# AJUSTAR` en la función
   `search_keyword()`, y reemplaza los selectores por los que copiaste.

💡 **Atajo aún mejor:** en la pestaña **Network** (Red) de las herramientas de
desarrollador, filtra por "Fetch/XHR", busca una palabra clave en la página,
y fíjate si aparece una petición a una URL tipo `.../api/...` que devuelva
JSON. Si la encuentras, es mucho más rápido y confiable usar esa URL
directamente con la librería `requests` en vez de Selenium — dime la URL y el
formato de la respuesta y te adapto el script para que sea más rápido y
liviano (sin necesitar Chrome).

---

## 📦 Instalación

```bash
cd seace_monitor
pip install -r requirements.txt
```

Necesitas tener **Google Chrome** instalado en tu computadora (el script
descarga automáticamente el driver compatible con `webdriver-manager`).

---

## 🔑 Configurar notificaciones

### Telegram
1. En Telegram, busca **@BotFather**, envía `/newbot` y sigue las instrucciones.
   Te dará un **token** (algo como `123456:ABC-def...`).
2. Busca **@userinfobot**, escríbele cualquier cosa, y te devuelve tu **chat_id**.
3. Abre una conversación con TU bot (búscalo por el nombre que le pusiste) y
   mándale un mensaje cualquiera (esto es necesario para que pueda escribirte).

### Correo (Gmail)
1. Activa la verificación en 2 pasos en tu cuenta de Gmail.
2. Crea una "Contraseña de aplicación" en:
   https://myaccount.google.com/apppasswords
3. Usa esa contraseña (no tu contraseña normal) en el archivo `.env`.

### Guardar tus datos
Copia `.env.example` como `.env` y completa tus valores:

```bash
cp .env.example .env
```

---

## ▶️ Uso

**Revisión única** (recomendado la primera vez, para probar):
```bash
python seace_monitor.py --no-headless
```
El `--no-headless` abre la ventana de Chrome para que veas qué está pasando
y confirmes que encuentra el campo de búsqueda y los resultados correctamente.
Una vez que funcione, puedes quitar `--no-headless` para que corra en segundo
plano sin abrir ventana.

**Revisión continua** (revisa cada 30 minutos, configurable en `.env`):
```bash
python seace_monitor.py --loop
```

---

## ⏰ Dejarlo corriendo automáticamente

En vez de tener la terminal abierta todo el día, es mejor programarlo:

### Windows (Programador de tareas)
1. Abre "Programador de tareas" → "Crear tarea básica".
2. Desencadenador: Diariamente, repetir cada 30 minutos.
3. Acción: Iniciar un programa → selecciona `python.exe` y en argumentos pon
   la ruta completa a `seace_monitor.py` (sin `--loop`, ya que la tarea se
   repite sola).

### Mac / Linux (cron)
```bash
crontab -e
```
Agrega una línea (revisa cada 30 min):
```
*/30 * * * * cd /ruta/a/seace_monitor && /usr/bin/python3 seace_monitor.py >> cron.log 2>&1
```

---

## ☁️ Dejarlo corriendo solo en GitHub (recomendado, gratis)

No necesitas tener tu compu prendida. GitHub tiene un programador de tareas
llamado **GitHub Actions** que puede abrir Chrome, correr el script, y
avisarte, todos los días, automáticamente. Así se configura:

### 1. Sube el proyecto a un repositorio de GitHub
```bash
cd seace_monitor
git init
git add .
git commit -m "Primera versión del monitor SEACE"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/seace-monitor.git
git push -u origin main
```
⚠️ Puede ser un repositorio **privado** (recomendado, ya que el código
menciona tus palabras clave de negocio) — GitHub Actions funciona igual en
repos privados y gratuitos.

### 2. Guarda tus datos secretos como "Secrets" (nunca como archivo .env)
En GitHub: entra a tu repositorio → **Settings** → **Secrets and variables**
→ **Actions** → **New repository secret**, y crea uno por cada variable:

| Nombre del secret     | Valor                                    |
|------------------------|-------------------------------------------|
| `TELEGRAM_BOT_TOKEN`   | el token de tu bot                        |
| `TELEGRAM_CHAT_ID`     | tu chat_id                                |
| `SMTP_HOST`            | `smtp.gmail.com`                          |
| `SMTP_PORT`            | `587`                                     |
| `EMAIL_FROM`           | tu correo Gmail                           |
| `EMAIL_PASSWORD`       | tu "Contraseña de aplicación" de Gmail    |
| `EMAIL_TO`             | a qué correo quieres que te avise         |

El archivo `.env` real **nunca se sube** al repositorio (ya está excluido en
`.gitignore`); solo `.env.example` (sin datos reales) queda como referencia.

### 3. El workflow ya está listo: `.github/workflows/seace_monitor.yml`
Ese archivo le dice a GitHub: "todos los días a las 8:05am hora Perú, instala
Chrome, instala las dependencias, y corre `seace_monitor.py`". También puedes
lanzarlo manualmente en cualquier momento desde la pestaña **Actions** de tu
repo → selecciona el workflow → **Run workflow**.

Para cambiar el horario, edita la línea `cron: "5 13 * * *"` (son minuto/hora
en UTC; Perú siempre es UTC-5, sin horario de verano).

### 4. Cómo recuerda lo que ya te avisó
Como cada corrida de GitHub Actions empieza "desde cero" (la máquina se borra
al terminar), el workflow guarda automáticamente `data/seen_items.json` de
vuelta en tu repositorio al final de cada ejecución, así la próxima corrida
sabe qué licitaciones ya te notificó.

### 5. Verifica que funcionó
Ve a la pestaña **Actions** de tu repositorio en GitHub: ahí verás cada
ejecución diaria, si tuvo errores, y los logs completos de lo que hizo.

---

## 🛠️ Personalizar palabras clave

Edita la lista `KEYWORDS` al inicio de `seace_monitor.py`. Ya incluye:
mochila(s), buzo(s), polo(s), textil(es), uniforme(s), confección,
indumentaria, chaleco(s), casaca(s), prendas — agrega o quita las que
necesites (por ejemplo "gorro", "guante", "chompa", "overol").

---

## 📁 Archivos que genera el programa

- `data/seen_items.json` — registro de licitaciones ya notificadas (para no
  avisarte dos veces lo mismo). Si lo borras, te volverá a avisar de todo.
- `data/monitor.log` — historial de lo que hizo el programa en cada revisión,
  útil para revisar si algo falló.

---

## ❓ Problemas comunes

- **"No se encontraron resultados visibles"**: el selector de la tabla no es
  el correcto, revisa el paso 4 de arriba.
- **No llega el mensaje de Telegram**: revisa que le hayas escrito primero a
  tu bot, y que el `TELEGRAM_CHAT_ID` sea el tuyo (no el del bot).
- **No llega el correo**: Gmail bloquea el login con la contraseña normal,
  asegúrate de usar la "Contraseña de aplicación".
- **El sitio pide CAPTCHA o bloquea el acceso automatizado**: reduce la
  frecuencia (`INTERVAL_MINUTES`) y evita correr `--loop` con intervalos muy
  cortos, para no parecer un bot agresivo.
