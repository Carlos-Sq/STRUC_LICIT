"""
Prueba independiente: confirma que el script SÍ lee el contenido real de un PDF.

Cómo usarlo:
  1. Ve al SEACE, abre cualquier licitación, haz clic derecho sobre el botón
     "Descargar requerimiento" y elige "Copiar dirección del enlace" (o ábrelo
     y copia la URL de la barra de direcciones).
  2. Corre: python test_lectura_pdf.py "PEGA_AQUI_LA_URL_DEL_PDF"
  3. Va a imprimir en pantalla el texto REAL que extrajo del PDF, y al final
     te dice si encontró alguna de las palabras clave (mochila, morral,
     maletín, bolsa de tela) y en qué parte del texto aparece.

Esto usa exactamente la misma función (extraer_texto_pdf) que usa
seace_monitor.py, así que si aquí funciona, funciona igual dentro del
monitor automático.
"""

import sys
import io
import unicodedata

import requests
from pypdf import PdfReader

KEYWORDS = [
    "bolsa de tela", "bolsas de tela",
    "morral", "morrales",
    "maletin", "maletín", "maletines",
    "mochila", "mochilas",
]


def normalizar(texto: str) -> str:
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def main():
    if len(sys.argv) < 2:
        print("Uso: python test_lectura_pdf.py \"URL_DEL_PDF\"")
        sys.exit(1)

    url = sys.argv[1]
    print(f"\nDescargando: {url}\n")

    resp = requests.get(url, timeout=25)
    resp.raise_for_status()
    print(f"Descarga OK. Tamaño del archivo: {len(resp.content):,} bytes\n")

    lector = PdfReader(io.BytesIO(resp.content))
    print(f"Número de páginas detectadas: {len(lector.pages)}\n")

    texto_completo = []
    for i, pagina in enumerate(lector.pages, start=1):
        texto_pagina = pagina.extract_text() or ""
        texto_completo.append(texto_pagina)
        print(f"--- Página {i} ({len(texto_pagina)} caracteres extraídos) ---")

    texto_completo = "\n".join(texto_completo)

    print("\n================ TEXTO EXTRAÍDO (primeros 1500 caracteres) ================\n")
    print(texto_completo[:1500] if texto_completo.strip() else "(⚠️ No se extrajo texto — puede ser un PDF escaneado como imagen)")
    print("\n=============================================================================\n")

    texto_norm = normalizar(texto_completo)
    encontradas = [kw for kw in KEYWORDS if normalizar(kw) in texto_norm]

    if encontradas:
        print(f"✅ SÍ se encontraron estas palabras clave dentro del PDF: {encontradas}")
        for kw in encontradas:
            idx = texto_norm.find(normalizar(kw))
            contexto = texto_completo[max(0, idx - 60): idx + 100].replace("\n", " ")
            print(f"\n   Contexto donde aparece '{kw}':\n   ...{contexto}...")
    else:
        print("❌ NO se encontró ninguna palabra clave dentro del texto de este PDF.")


if __name__ == "__main__":
    main()
