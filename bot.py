import os
import json
import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime
from urllib.parse import quote, urlparse, urljoin
from bs4 import BeautifulSoup

# ⚙️ CONFIGURACIÓN
MODO_TURBO = True
NOTICIAS_POR_CARRERA = 10 if MODO_TURBO else 1
RSS_URL = "https://news.google.com/rss/search?q=when:1d+geo:Mexico&hl=es-419&gl=MX&ceid=MX:es-419"
JSON_PATH = "data/noticias.json"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-MX,es;q=0.9,en;q=0.8',
    'Referer': 'https://www.google.com/',
}

# Usar una sesión global ayuda a simular un navegador real
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

def decodificar_url_google(url):
    """
    Decodifica la URL ofuscada de Google News usando peticiones y BeautifulSoup.
    """
    try:
        if 'news.google.com' not in url:
            return url

        # Intentar seguir redirección con requests
        r = session.get(url, timeout=10, allow_redirects=True)
        
        # Si la URL final ya no es de Google, la tenemos
        if 'google.com' not in r.url and 'google.com' not in urlparse(r.url).netloc:
            return r.url
            
        # Buscar la URL real (canonical) usando BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 1. Buscar etiqueta canonical (método más seguro)
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href") and 'google' not in canonical.get("href"):
            return canonical.get("href")
            
        # 2. Buscar enlaces directos en la página de redirección de Google
        links = soup.find_all("a")
        for link in links:
            href = link.get("href", "")
            if href.startswith("http") and 'google' not in href and len(href) > 20:
                return href

        # 3. Fallback a Regex original por si falla BS4
        patterns = [
            r'<c-wiz[^>]*>\s*<a[^>]+href=["\'](https?://(?!.*google\.com)[^"\']+)["\']',
            r'"url":"(https?://(?!.*google\.com)[^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, r.text)
            if match:
                candidate = match.group(1)
                if len(candidate) > 20 and 'google' not in candidate:
                    return candidate
                    
    except Exception as e:
        print(f"   ⚠️ Error decodificando URL: {e}")
    return None

def extraer_imagen_de_articulo(url_real):
    """Extrae og:image usando BeautifulSoup para mayor precisión y une URLs relativas."""
    if not url_real:
        return None
    try:
        r = session.get(url_real, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return None
            
        soup = BeautifulSoup(r.text, 'html.parser')

        # Buscar og:image y twitter:image
        selectores = [
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:image:url"}
        ]
        
        for sel in selectores:
            meta = soup.find("meta", attrs=sel)
            if meta and meta.get("content"):
                img = meta.get("content").split('?')[0] # Limpiar parámetros
                if 'google' not in img and 'logo' not in img.lower() and 'icon' not in img.lower() and len(img) > 10:
                    # urljoin soluciona el problema de las rutas relativas (/img/foto.jpg -> https://sitio.com/img/foto.jpg)
                    return urljoin(url_real, img)
                    
        # Fallback: buscar la imagen más grande dentro del contenido
        imgs = soup.find_all("img")
        for img_tag in imgs:
            src = img_tag.get("src") or img_tag.get("data-src")
            if src and len(src) > 40 and 'logo' not in src.lower() and 'icon' not in src.lower():
                return urljoin(url_real, src)

    except Exception as e:
        print(f"   ⚠️ Error extrayendo imagen: {e}")
    return None

def imagen_fallback(titulo):
    """Fallback: imagen temática de Picsum basada en seed del título."""
    seed = abs(hash(titulo)) % 9999
    return f"https://picsum.photos/seed/{seed}/800/500"

def obtener_imagen(titulo, url_google):
    """Pipeline completo para obtener imagen relevante de la noticia."""
    print(f"   🔗 Decodificando URL de Google News...")
    url_real = decodificar_url_google(url_google)
    
    if url_real:
        print(f"   🌐 URL real: {url_real[:65]}...")
        img = extraer_imagen_de_articulo(url_real)
        if img:
            print(f"   🖼️ Imagen extraída del artículo ✅")
            return img, url_real
        else:
            print(f"   ⚠️ No se encontró imagen en el artículo, usando fallback")
    else:
        print(f"   ⚠️ No se pudo decodificar la URL, usando fallback")
    
    return imagen_fallback(titulo), url_google

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
    try:
        res = session.get(RSS_URL, timeout=10)
        root = ET.fromstring(res.content)
    except Exception as e:
        print(f"❌ Error RSS: {e}")
        return

    noticias_guardadas = cargar_noticias()
    nuevos = 0

    for item in root.findall(".//item")[:NOTICIAS_POR_CARRERA]:
        t_orig = item.find("title").text

        link_elem = item.find("link")
        link_google = ""
        if link_elem is not None and link_elem.text:
            link_google = link_elem.text
        else:
            for child in item:
                if child.tag == 'link' and child.tail:
                    link_google = child.tail.strip()
                    break

        if not link_google:
            guid = item.find("guid")
            if guid is not None and guid.text:
                link_google = guid.text

        if any(n.get('titulo_original') == t_orig for n in noticias_guardadas):
            continue

        print(f"\n🔄 Procesando: {t_orig[:60]}...")
        t_ia, r_ia, c_ia = reescribir_con_ia(t_orig)

        img_url, url_real = obtener_imagen(t_ia, link_google)

        nuevo_id = max([n["id"] for n in noticias_guardadas], default=0) + 1
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
        print(f"✅ Guardada: {t_ia[:50]} ({len(c_ia.split())} palabras)")

    if nuevos > 0:
        if len(noticias_guardadas) > 100:
            noticias_guardadas = noticias_guardadas[-100:]
        guardar_noticias(noticias_guardadas)
        print(f"\n💾 Guardadas {nuevos} noticias nuevas.")
    else:
        print("ℹ️ No hay noticias nuevas.")

if __name__ == "__main__":
    ejecutar()
