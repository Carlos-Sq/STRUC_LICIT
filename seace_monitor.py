"""
SEACE Monitor - Vigilante de licitaciones de mochilas / textiles
==================================================================

Qué hace:
  1. Abre el Buscador de Contrataciones Menores del SEACE
     (https://prod6.seace.gob.pe/buscador-publico/contrataciones)
  2. Busca, una por una, las palabras clave definidas en KEYWORDS
     (mochila, morral, maletín, bolsa de tela)
  3. Extrae los resultados de cada búsqueda (entidad, descripción, monto, fecha, link)
  4. Descarga el PDF de "Descargar requerimiento" de cada resultado nuevo y
     revisa si el texto realmente contiene alguna de las palabras clave
     (esto evita avisos de licitaciones que solo mencionan la palabra de
     pasada en el título pero no son realmente del producto buscado, o que
     el buscador del sitio trajo por error).
  5. Compara contra un registro local (seen_items.json) para saber cuáles son NUEVOS
  6. Si hay resultados nuevos y verificados, te avisa por Telegram y por Correo

Cómo se ejecuta:
  - Una sola vez:      python seace_monitor.py
  - En bucle continuo: python seace_monitor.py --loop   (revisa cada INTERVALO minutos)

IMPORTANTE — LEE ESTO ANTES DE USARLO:
  El sitio del SEACE es una aplicación Angular (SPA), así que no se puede leer
  el HTML directamente con "requests": hay que controlar un navegador real
  (Chrome) con Selenium para que la página cargue el JavaScript y muestre
  los resultados, igual que cuando tú entras desde el navegador.

  Los "selectores" (los nombres de las cajas de búsqueda y las columnas de la
  tabla de resultados) los marqué con # AJUSTAR más abajo. Es MUY probable que
  tengas que abrir la página en Chrome, presionar F12 (Inspeccionar), hacer clic
  derecho sobre el campo de búsqueda y sobre una fila de resultados, elegir
  "Inspeccionar", y copiar el atributo id/class/name real que veas ahí, porque
  el sitio del Estado puede cambiar sin aviso. Te dejé instrucciones detalladas
  en el README para hacer esto paso a paso, no toma más de 5 minutos.

  NOTA sobre la verificación por PDF: el enlace "Descargar requerimiento" y su
  atributo href se leen de cada tarjeta de resultado. Si el sitio cambia el
  texto de ese botón o requiere sesión/login para descargar el PDF, revisa la
  función find_requerimiento_link() y verificar_requerimiento_pdf() más abajo.
"""

import argparse
import io
import json
import logging
import os
import re
import smtplib
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

import requests
from dotenv import load_dotenv
from pypdf import PdfReader
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

load_dotenv()  # carga variables desde el archivo .env

SEACE_URL = "https://prod6.seace.gob.pe/buscador-publico/contrataciones"

# Palabras clave. Se dejaron solo las que pediste, con singular/plural para
# no perder resultados por una diferencia de género/número en el título.
KEYWORDS = [
    "bolsa de tela",
    "bolsas de tela",
    "morral",
    "morrales",
    "maletin",
    "maletín",
    "maletines",
    "mochila",
    "mochilas",
]

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
SEEN_FILE = DATA_DIR / "seen_items.json"

INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES") or "30")

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Correo (SMTP) ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT") or "587")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # usar "Contraseña de aplicación" de Gmail
EMAIL_TO = os.getenv("EMAIL_TO", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "monitor.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("seace_monitor")


PERU_TZ = timezone(timedelta(hours=-5))  # SEACE publica horas en huso horario de Perú


def _cotizacion_sigue_vigente(cotizaciones_texto: str) -> bool:
    """
    Revisa el texto del campo "Cotizaciones" (ej. "04/08/2026 00:01:00 - 05/08/2026 23:59:00")
    y devuelve False si la fecha/hora de FIN ya pasó respecto a ahora (hora Perú).

    Si el texto no se puede interpretar, se devuelve True (no se descarta el
    resultado) para evitar perder oportunidades válidas por un error de parseo.
    """
    if not cotizaciones_texto:
        return True

    partes = cotizaciones_texto.split(" - ")
    texto_fin = partes[-1].strip() if partes else ""

    match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})", texto_fin)
    if not match:
        return True

    try:
        fecha_fin = datetime.strptime(
            f"{match.group(1)} {match.group(2)}", "%d/%m/%Y %H:%M:%S"
        ).replace(tzinfo=PERU_TZ)
    except ValueError:
        return True

    ahora = datetime.now(PERU_TZ)
    return fecha_fin >= ahora


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar 'maletín' == 'maletin'."""
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def pdf_contiene_palabra_clave(texto_pdf: str) -> str | None:
    """Devuelve la primera palabra clave encontrada en el texto del PDF, o None."""
    texto_norm = _normalizar(texto_pdf)
    for kw in KEYWORDS:
        if _normalizar(kw) in texto_norm:
            return kw
    return None


@dataclass
class Contratacion:
    id: str
    codigo: str
    entidad: str
    descripcion: str
    cotizaciones: str
    fecha_publicacion: str
    estado: str
    link: str
    keyword: str

    def to_text(self) -> str:
        return (
            f"🎒 Nueva licitación relacionada a textil/mochilas\n\n"
            f"Código: {self.codigo}\n"
            f"Entidad: {self.entidad}\n"
            f"Descripción: {self.descripcion}\n"
            f"Cotizaciones: {self.cotizaciones}\n"
            f"Fecha de publicación: {self.fecha_publicacion}\n"
            f"Estado: {self.estado}\n"
            f"Palabra clave: {self.keyword}\n"
            f"Link: {self.link}"
        )


# ---------------------------------------------------------------------------
# NAVEGADOR (SELENIUM)
# ---------------------------------------------------------------------------

def build_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1366,900")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def build_http_session_from_driver(driver: webdriver.Chrome) -> requests.Session:
    """
    Crea una sesión de 'requests' que copia las cookies del navegador de
    Selenium, para poder descargar los PDF de requerimiento (por si el sitio
    exige alguna cookie de sesión para servir el archivo).
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            )
        }
    )
    try:
        for cookie in driver.get_cookies():
            session.cookies.set(cookie.get("name"), cookie.get("value"))
    except Exception as e:
        log.warning("No se pudieron copiar las cookies del navegador a la sesión HTTP: %s", e)
    return session


def _find_filter_checkbox(driver, formgroupname_candidates: list[str], option_text: str):
    """
    Ubica la casilla de un filtro del sitio (que usa Angular Material - <mat-checkbox>)
    dentro del bloque <div formgroupname="..."> correspondiente, buscando la que
    tiene el texto visible indicado (ej. "Bien", "Vigente").

    formgroupname_candidates: lista de nombres posibles del formgroup (el sitio
    confirmó "objetos" para la sección Objeto; para Estado se prueban varios
    nombres razonables por si no coincide exactamente).
    """
    for fg in formgroupname_candidates:
        try:
            contenedor = driver.find_element(By.CSS_SELECTOR, f"[formgroupname='{fg}']")
        except Exception:
            continue

        casillas = contenedor.find_elements(By.TAG_NAME, "mat-checkbox")
        for casilla in casillas:
            try:
                if casilla.text.strip().lower() == option_text.strip().lower():
                    return casilla
            except Exception:
                continue

    # Respaldo: si no se encontró por formgroupname, busca cualquier
    # <mat-checkbox> en la página cuyo texto coincida exactamente.
    try:
        for casilla in driver.find_elements(By.TAG_NAME, "mat-checkbox"):
            if casilla.text.strip().lower() == option_text.strip().lower():
                return casilla
    except Exception:
        pass

    raise Exception(f"No se encontró la casilla '{option_text}' (formgroups probados: {formgroupname_candidates})")


def _is_mat_checkbox_checked(mat_checkbox_el) -> bool:
    """Detecta si un <mat-checkbox> de Angular Material está marcado."""
    try:
        cls = mat_checkbox_el.get_attribute("class") or ""
        if "mat-mdc-checkbox-checked" in cls:
            return True
    except Exception:
        pass
    try:
        input_el = mat_checkbox_el.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
        return input_el.is_selected()
    except Exception:
        pass
    return False


def ensure_filters(driver: webdriver.Chrome) -> None:
    """
    Verifica que los filtros "Objeto: Bien" y "Estado: Vigente" estén
    marcados antes de cada búsqueda (requisito indicado por el usuario).
    Si por algún motivo no lo están, hace clic para marcarlos.

    Confirmado en el sitio: la sección "Objeto" vive en <div formgroupname="objetos">.
    Para "Estado" se prueban varios nombres posibles de formgroup por si el
    sitio usa una convención distinta (ej. "estados", "estado").
    """
    filtros = [
        (["objetos", "objeto"], "Bien"),
        (["estados", "estado"], "Vigente"),
    ]
    for formgroups, opcion in filtros:
        try:
            casilla = _find_filter_checkbox(driver, formgroups, opcion)
            if not _is_mat_checkbox_checked(casilla):
                # Click sobre el label interno del mat-checkbox (más confiable
                # que el host en Angular Material).
                try:
                    casilla.find_element(By.CSS_SELECTOR, "label").click()
                except Exception:
                    casilla.click()
                log.info("Filtro '%s' no estaba marcado, se marcó ahora.", opcion)
                time.sleep(0.5)
        except Exception as e:
            log.warning(
                "No se pudo verificar/marcar el filtro '%s' (%s). "
                "Revisa manualmente que esté marcado en el sitio.",
                opcion, e,
            )


def find_requerimiento_link(tarjeta) -> str | None:
    """
    Busca dentro de la tarjeta el enlace/botón "Descargar requerimiento" y
    devuelve su href (la URL del PDF). Si no lo encuentra, devuelve None.

    # AJUSTAR: si el sitio cambia el texto del botón (ej. "Descargar bases",
    # "Ver requerimiento", etc.) o lo convierte en un <button> con JS en vez
    # de un <a href>, hay que actualizar este selector.
    """
    try:
        a_tag = tarjeta.find_element(By.XPATH, ".//a[contains(., 'Descargar requerimiento')]")
        href = a_tag.get_attribute("href")
        if href:
            return href
    except Exception:
        pass
    return None


def extraer_texto_pdf(pdf_bytes: bytes) -> str:
    """Extrae el texto de un PDF (bytes) usando pypdf."""
    lector = PdfReader(io.BytesIO(pdf_bytes))
    paginas_texto = []
    for pagina in lector.pages:
        try:
            paginas_texto.append(pagina.extract_text() or "")
        except Exception:
            continue
    return "\n".join(paginas_texto)


def verificar_requerimiento_pdf(session: requests.Session, url_pdf: str) -> tuple[bool, str]:
    """
    Descarga el PDF del requerimiento y revisa si contiene alguna de las
    KEYWORDS. Devuelve (coincide, motivo).

    Si algo falla (descarga, PDF escaneado sin texto, etc.) se devuelve
    (True, motivo) para NO descartar la oportunidad por un problema técnico:
    en ese caso se notifica igual, basado en la coincidencia del título/
    descripción, y se deja registrado en el log que no se pudo verificar.
    """
    try:
        resp = session.get(url_pdf, timeout=25)
        resp.raise_for_status()
        texto = extraer_texto_pdf(resp.content)
        if not texto.strip():
            return True, "pdf_sin_texto_legible"
        encontrada = pdf_contiene_palabra_clave(texto)
        if encontrada:
            return True, f"coincide_en_pdf:{encontrada}"
        return False, "pdf_no_contiene_palabras_clave"
    except Exception as e:
        log.warning("No se pudo descargar/leer el PDF de requerimiento (%s): %s", url_pdf, e)
        return True, "error_al_verificar_pdf"


def search_keyword(
    driver: webdriver.Chrome,
    keyword: str,
    http_session: requests.Session | None = None,
) -> list[Contratacion]:
    """
    Busca una palabra clave en el buscador del SEACE (con los filtros
    Objeto=Bien y Estado=Vigente siempre marcados) y devuelve
    los resultados encontrados como tarjetas, verificados contra el PDF de
    requerimiento cuando es posible.
    """
    wait = WebDriverWait(driver, 25)

    # NOTA: no se navega de nuevo a SEACE_URL aquí a propósito: recargar la
    # página en cada palabra clave sería más lento y podría resetear los
    # filtros. Se reutiliza la misma página y sólo se cambia el texto buscado.

    # 1) Escribir la palabra clave en el campo de búsqueda.
    # Confirmado en el sitio: el campo es un componente <osce-input-search>
    # con un <input> que tiene este aria-label fijo (más confiable que clases
    # generadas automáticamente por Angular, que sí pueden cambiar).
    try:
        search_box = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[aria-label='Buscar por descripción, objeto, número o entidad contratante']")
            )
        )
    except Exception:
        # Respaldo por si el aria-label cambia ligeramente.
        search_box = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "osce-input-search input[type='text']"))
        )
    search_box.clear()
    search_box.send_keys(keyword)

    # 2) IMPORTANTE: asegurar que "Bien" (Objeto) y "Vigente" (Estado) estén
    #    marcados SIEMPRE antes de ejecutar la búsqueda.
    ensure_filters(driver)

    # 3) Ejecutar la búsqueda. Se usa Enter como método principal (más
    #    confiable para cajas de búsqueda reactivas de Angular); si eso no
    #    dispara nada, se intenta clic en el ícono de lupa como respaldo.
    from selenium.webdriver.common.keys import Keys
    search_box.send_keys(Keys.ENTER)
    time.sleep(0.3)
    try:
        icono_lupa = driver.find_element(By.CSS_SELECTOR, ".osce-input-search__icon")
        icono_lupa.click()
    except Exception:
        pass

    # 4) Esperar a que aparezcan las tarjetas de resultado, identificadas por
    #    el texto "Cotizaciones:" que aparece en cada una.
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'Cotizaciones:') or contains(text(), 'contrataciones encontradas')]")
            )
        )
    except Exception:
        log.warning("No cargó la sección de resultados para '%s' (o cambió el layout).", keyword)
        return []

    time.sleep(2.5)  # colchón más amplio para que Angular termine de refrescar la lista

    # Si el sitio indica "0 contrataciones encontradas", no hay nada que parsear.
    try:
        resumen = driver.find_element(By.XPATH, "//*[contains(text(), 'contrataciones encontradas')]").text
        if resumen.strip().lower().startswith("0"):
            return []
    except Exception:
        pass

    # 5) Cada tarjeta de resultado contiene el texto "Cotizaciones:". Se ubica
    #    ese nodo y se sube hasta el contenedor de la tarjeta completa (el que
    #    también incluye el botón "Ver detalle").
    cotiz_nodes = driver.find_elements(By.XPATH, "//*[contains(text(), 'Cotizaciones:')]")

    resultados = []
    tarjetas_vistas = set()
    for node in cotiz_nodes:
        try:
            tarjeta = node.find_element(
                By.XPATH, "ancestor::*[.//text()[contains(., 'Ver detalle')]][1]"
            )
        except Exception:
            continue

        # Evitar procesar la misma tarjeta más de una vez si el XPath la repite.
        tarjeta_ref = tarjeta.id
        if tarjeta_ref in tarjetas_vistas:
            continue
        tarjetas_vistas.add(tarjeta_ref)

        try:
            texto_completo = tarjeta.text
            lineas = [l.strip() for l in texto_completo.split("\n") if l.strip()]

            LABELS = ("bien:", "servicio:", "obra:", "consultoría de obra:", "consultoria de obra:")
            ESTADOS = ("vigente", "en evaluación", "en evaluacion", "culminado")
            OTROS_A_IGNORAR = ("cotizaciones:", "fecha de publicación:", "fecha de publicacion:",
                                "ver detalle", "descargar requerimiento")

            codigo = lineas[0] if lineas else ""
            entidad = ""
            descripcion = ""
            cotizaciones = ""
            fecha_publicacion = ""
            estado = ""

            # Se recorren las líneas (salvo el código) sin asumir una posición
            # fija, porque la etiqueta de estado ("Vigente") puede aparecer en
            # distintos lugares del texto según cómo esté maquetada la tarjeta.
            for linea in lineas[1:]:
                l_lower = linea.lower()
                if l_lower in ESTADOS:
                    estado = linea
                elif l_lower.startswith(LABELS):
                    descripcion = linea.split(":", 1)[1].strip()
                elif l_lower.startswith("cotizaciones:"):
                    cotizaciones = linea.split(":", 1)[1].strip()
                elif l_lower.startswith(("fecha de publicación:", "fecha de publicacion:")):
                    fecha_publicacion = linea.split(":", 1)[1].strip()
                elif not entidad and not l_lower.startswith(OTROS_A_IGNORAR):
                    # La primera línea "libre" (que no es una etiqueta conocida
                    # ni el estado) es el nombre de la entidad.
                    entidad = linea

            link = SEACE_URL
            try:
                a_tag = tarjeta.find_element(By.XPATH, ".//a[contains(., 'Ver detalle')]")
                link = a_tag.get_attribute("href") or SEACE_URL
            except Exception:
                pass

            uid = f"{codigo}|{entidad}|{descripcion}".strip()
            if not uid or not descripcion:
                continue

            # 🔒 FILTRO 1: pase lo que pase con el buscador del sitio (si por
            # algún motivo no filtró bien), NUNCA se notifica un resultado que
            # no contenga realmente la palabra clave buscada.
            texto_para_verificar = f"{codigo} {entidad} {descripcion}".lower()
            if keyword.lower() not in texto_para_verificar:
                log.debug(
                    "Descartado por seguridad (no contiene '%s'): %s",
                    keyword, descripcion[:60],
                )
                continue

            # 🔒 FILTRO 2: no notificar si el plazo para presentar cotización
            # ya venció (aunque el sitio lo siga marcando como "Vigente").
            if not _cotizacion_sigue_vigente(cotizaciones):
                log.debug(
                    "Descartado por fecha vencida (%s): %s",
                    cotizaciones, descripcion[:60],
                )
                continue

            # 🔒 FILTRO 3: revisar el PDF de "Descargar requerimiento" y
            # confirmar que realmente trata sobre mochila/morral/maletín/
            # bolsa de tela, no solo que la palabra aparezca de pasada en el
            # título. Si no hay sesión HTTP o no se encuentra el enlace, se
            # notifica igual (basado en el título) y se deja constancia en el log.
            if http_session is not None:
                url_pdf = find_requerimiento_link(tarjeta)
                if url_pdf:
                    coincide, motivo = verificar_requerimiento_pdf(http_session, url_pdf)
                    if not coincide:
                        log.info(
                            "Descartado tras revisar el PDF de requerimiento (%s): %s",
                            motivo, descripcion[:60],
                        )
                        continue
                    else:
                        log.debug("PDF verificado (%s): %s", motivo, descripcion[:60])
                else:
                    log.debug(
                        "No se encontró enlace 'Descargar requerimiento'; se notifica solo por título: %s",
                        descripcion[:60],
                    )

            resultados.append(
                Contratacion(
                    id=uid,
                    codigo=codigo,
                    entidad=entidad,
                    descripcion=descripcion,
                    cotizaciones=cotizaciones,
                    fecha_publicacion=fecha_publicacion,
                    estado=estado,
                    link=link,
                    keyword=keyword,
                )
            )
        except Exception as e:
            log.debug("Tarjeta ignorada por error de parseo: %s", e)
            continue

    return resultados


# ---------------------------------------------------------------------------
# PERSISTENCIA (evitar avisar dos veces lo mismo)
# ---------------------------------------------------------------------------

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# NOTIFICACIONES
# ---------------------------------------------------------------------------

def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram no configurado (falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env)")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
        if resp.status_code != 200:
            log.error("Error enviando Telegram: %s %s", resp.status_code, resp.text)
    except Exception as e:
        log.error("Excepción enviando Telegram: %s", e)


def send_email(subject: str, body: str) -> None:
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        log.warning("Correo no configurado (falta EMAIL_FROM/EMAIL_PASSWORD/EMAIL_TO en .env)")
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
    except Exception as e:
        log.error("Excepción enviando correo: %s", e)


def notify(item: Contratacion) -> None:
    texto = item.to_text()
    send_telegram(texto)
    send_email(subject=f"Nueva licitación: {item.keyword}", body=texto)
    log.info("Notificación enviada: %s | %s", item.entidad, item.descripcion[:60])


# ---------------------------------------------------------------------------
# CICLO PRINCIPAL
# ---------------------------------------------------------------------------

def run_once(headless: bool = True) -> None:
    log.info("Iniciando revisión del SEACE (%d palabras clave)...", len(KEYWORDS))
    seen = load_seen()
    nuevos_total = 0

    driver = build_driver(headless=headless)
    try:
        driver.get(SEACE_URL)
        wait_inicial = WebDriverWait(driver, 25)
        # Espera a que cargue el input real (confirma que Angular ya renderizó
        # el formulario) en vez de un time.sleep fijo.
        try:
            wait_inicial.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "osce-input-search input[type='text']"))
            )
        except Exception:
            log.warning("La página tardó en cargar el buscador; se continúa de todos modos.")
        time.sleep(1)
        ensure_filters(driver)  # confirma Objeto=Bien y Estado=Vigente antes de empezar

        http_session = build_http_session_from_driver(driver)

        for kw in KEYWORDS:
            log.info("Buscando: '%s'", kw)
            try:
                resultados = search_keyword(driver, kw, http_session=http_session)
            except Exception as e:
                log.error("Error buscando '%s': %s", kw, e)
                continue

            for item in resultados:
                if item.id not in seen:
                    seen.add(item.id)
                    nuevos_total += 1
                    notify(item)

            time.sleep(2)  # pausa breve entre búsquedas para no saturar el sitio
    finally:
        driver.quit()

    save_seen(seen)
    log.info("Revisión terminada. Resultados nuevos notificados: %d", nuevos_total)


def main():
    parser = argparse.ArgumentParser(description="Monitor de licitaciones SEACE (mochilas/textil)")
    parser.add_argument("--loop", action="store_true", help="Ejecutar en bucle continuo")
    parser.add_argument("--no-headless", action="store_true", help="Mostrar la ventana de Chrome (para depurar)")
    args = parser.parse_args()

    headless = not args.no_headless

    if args.loop:
        log.info("Modo bucle activado. Revisando cada %d minutos.", INTERVAL_MINUTES)
        while True:
            run_once(headless=headless)
            log.info("Durmiendo %d minutos...", INTERVAL_MINUTES)
            time.sleep(INTERVAL_MINUTES * 60)
    else:
        run_once(headless=headless)


if __name__ == "__main__":
    main()
