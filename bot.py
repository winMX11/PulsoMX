import os
import json
import requests
import xml.etree.ElementTree as ET
import re
import time  # ⏱️ Añadido para controlar el límite de la API
from datetime import datetime
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

# ⚙️ CONFIGURACIÓN
MODO_TURBO = True
NOTICIAS_POR_CARRERA = 10 if MODO_TURBO else 1

# 🔥 RSS directos de fuentes mexicanas.
RSS_FEEDS = [
    "https://aristeguinoticias.com/feed/",
    "https://www.proceso.com.mx/rss/feed.html",
    "https://expansion.mx/rss",
    "https://www.jornada.com.mx/rss/edicion.xml?v=1"
]

JSON_PATH = "data/noticias.json"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-MX,es;q=0.9,en;q=0.8',
}

session = requests.Session()
session.headers.update(HEADERS)

def cargar_noticias():
    if not os.path.exists(JSON_PATH): return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return []

def guardar_noticias(noticias):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)

def extraer_imagen_de_articulo(url_real):
    if not url_real:
        return None
    try:
        r = session.get(url_real, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return None
            
        soup = BeautifulSoup(r.text, 'html.parser')

        selectores = [
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:image:url"}
        ]
        
        for sel in selectores:
            meta = soup.find("meta", attrs=sel)
            if meta and meta.get("content"):
                img = meta.get("content").split('?')[0] 
                if 'logo' not in img.lower() and 'icon' not in img.lower() and len(img) > 10:
                    return urljoin(url_real, img)
                    
        imgs = soup.find_all("img")
        for img_tag in imgs:
            src = img_tag.get("src") or img_tag.get("data-src")
            if src and len(src) > 40 and 'logo' not in src.lower() and 'icon' not in src.lower():
                return urljoin(url_real, src)

    except Exception as e:
        print(f"   ⚠️ Error extrayendo imagen: {e}")
    return None

def imagen_fallback(titulo):
    seed = abs(hash(titulo)) % 9999
    return f"https://picsum.photos/seed/{seed}/800/500"

def obtener_imagen(titulo, url_real):
    print(f"   🌐 URL directa: {url_real[:65]}...")
    img = extraer_imagen_de_articulo(url_real)
    
    if img:
        print(f"   🖼️ Imagen extraída del artículo ✅")
        return img, url_real
    else:
        print(f"   ⚠️ No se encontró imagen en el artículo, usando fallback")
        return imagen_fallback(titulo), url_real

def reescribir_con_ia(titulo_orig):
    if not GROQ_API_KEY:
        return titulo_orig, "Noticia reciente.", "Detalles en el enlace original."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""Eres un periodista profesional mexicano. A partir del siguiente titular de noticia, genera un artículo periodístico completo en español.

TITULAR: {titulo_orig}

Instrucciones OBLIGATORIAS:
- El "titulo" debe ser atractivo, claro y en español, máximo 90 caracteres.
- El "resumen" debe ser un párrafo de 3-4 oraciones que explique el contexto general de la noticia, quiénes son los involucrados y por qué es importante. Mínimo 80 palabras.
- El "contenido" debe ser un artículo periodístico completo de MÍNIMO 500 palabras con:
  * Párrafo de introducción que responda: ¿qué pasó?, ¿quién?, ¿cuándo?, ¿dónde?
  * Al menos 4 párrafos de desarrollo con contexto, antecedentes, detalles relevantes e impacto
  * Citas o declaraciones probables de los involucrados (puedes inferirlas de forma periodística)
  * Párrafo de cierre con perspectivas o lo que se espera a futuro
  * Usa párrafos separados por saltos de línea (\\n\\n)
  * Escribe en tono periodístico formal pero accesible para el público mexicano general

Responde ÚNICAMENTE con un JSON válido con estas tres claves exactas: "titulo", "resumen", "contenido". Sin texto extra, sin markdown, sin explicaciones."""

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
        "max_tokens": 2000
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=45)
        res = r.json()
        
        # 🛠️ Manejo de errores si Groq bloquea por límite de peticiones
        if 'choices' not in res:
            print(f"   ⚠️ API Groq Error: {res.get('error', {}).get('message', 'Límite alcanzado o error desconocido')}")
            return titulo_orig, "Noticia en desarrollo.", "Revisa el enlace original para más detalles."

        contenido_crudo = res['choices'][0]['message']['content']
        data = json.loads(contenido_crudo)
        titulo = data.get("titulo", titulo_orig)[:120]
        resumen = data.get("resumen", "Noticia importante de México.")
        contenido = data.get("contenido", "Revisa el enlace original para más detalles.")
        if len(contenido.split()) < 200:
            contenido += "\n\n" + resumen
        return titulo, resumen, contenido
    except Exception as e:
        print(f"⚠️ Error IA: {e}")
        return titulo_orig, "Noticia importante de México.", "Revisa el enlace original para más detalles."

def ejecutar():
    noticias_guardadas = cargar_noticias()
    nuevos = 0
    noticias_procesadas = 0

    for feed_url in RSS_FEEDS:
        if noticias_procesadas >= NOTICIAS_POR_CARRERA:
            break
            
        try:
            res = session.get(feed_url, timeout=10)
            res.encoding = res.apparent_encoding 
            root = ET.fromstring(res.text)
        except Exception as e:
            print(f"❌ Error leyendo feed {feed_url}: {e}")
            continue

        for item in root.findall(".//item"):
            if noticias_procesadas >= NOTICIAS_POR_CARRERA:
                break
                
            t_orig = item.find("title").text
            if not t_orig: continue

            link_elem = item.find("link")
            link_directo = ""
            if link_elem is not None and link_elem.text:
                link_directo = link_elem.text
            else:
                for child in item:
                    if child.tag == 'link' and child.tail:
                        link_directo = child.tail.strip()
                        break
            
            if not link_directo:
                guid = item.find("guid")
                if guid is not None and guid.text:
                    link_directo = guid.text

            if any(n.get('titulo_original') == t_orig for n in noticias_guardadas):
                continue

            print(f"\n🔄 Procesando: {t_orig[:60]}...")
            t_ia, r_ia, c_ia = reescribir_con_ia(t_orig)

            img_url, url_real = obtener_imagen(t_ia, link_directo)

            nuevo_id = max([n.get("id", 0) for n in noticias_guardadas], default=0) + 1
            noticias_guardadas.append({
                "id": nuevo_id,
                "titulo_original": t_orig,
                "titulo": t_ia,
                "resumen": r_ia,
                "contenido": c_ia,
                "imagen": img_url,
                "fecha": datetime.today().strftime('%Y-%m-%d'),
                "url_origen": url_real
            })
            nuevos += 1
            noticias_procesadas += 1
            print(f"✅ Guardada: {t_ia[:50]} ({len(c_ia.split())} palabras)")
            
            # ⏱️ Pausa obligatoria para evitar el bloqueo de Groq (Rate Limit)
            time.sleep(4)

    if nuevos > 0:
        if len(noticias_guardadas) > 100:
            noticias_guardadas = noticias_guardadas[-100:]
        guardar_noticias(noticias_guardadas)
        print(f"\n💾 Guardadas {nuevos} noticias nuevas.")
    else:
        print("ℹ️ No hay noticias nuevas.")

if __name__ == "__main__":
    ejecutar()
