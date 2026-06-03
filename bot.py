import os
import json
import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime
from urllib.parse import quote
from bs4 import BeautifulSoup  # Nueva librería

# ⚙️ CONFIGURACIÓN
MODO_TURBO = True
NOTICIAS_POR_CARRERA = 10 if MODO_TURBO else 1
RSS_URL = "https://news.google.com/rss/search?q=when:1d+geo:Mexico&hl=es-419&gl=MX&ceid=MX:es-419"
JSON_PATH = "data/noticias.json"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Headers para que los sitios web crean que somos un navegador
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

def cargar_noticias():
    if not os.path.exists(JSON_PATH): return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return []

def guardar_noticias(noticias):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)

def obtener_imagen_real(url):
    try:
        # Aumentamos el timeout y los headers para parecer más un navegador real
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"⚠️ No pude entrar a la noticia (Código {response.status_code}): {url}")
            return "https://images.unsplash.com/photo-1504711434269-d0385429813a?q=80&w=800&auto=format&fit=crop"

        soup = BeautifulSoup(response.content, 'html.parser')

        # Lista de lugares donde los periódicos suelen esconder la imagen
        posibles_tags = [
            soup.find("meta", property="og:image"),
            soup.find("meta", property="twitter:image"),
            soup.find("meta", name="twitter:image"),
            soup.find("link", rel="image_src"),
            soup.find("meta", itemprop="image")
        ]

        # Intentamos obtener el contenido de cada una
        for tag in posibles_tags:
            if tag and tag.get("content"):
                imagen = tag["content"]
                # A veces la imagen es relativa (empieza por /), arreglémosla
                if imagen.startswith("/"):
                    from urllib.parse import urljoin
                    imagen = urljoin(url, imagen)
                return imagen

        # Si llegamos aquí, no encontramos tags meta. 
        # Último intento: buscar la primera imagen grande en el body (muy arriesgado pero efectivo)
        img_tag = soup.find("img", class_=lambda x: x and ('article' in x or 'post' in x or 'photo' in x))
        if img_tag and img_tag.get("src"):
            return img_tag["src"]

        print(f"❌ No encontré imagen en: {url}")
        return "https://images.unsplash.com/photo-1504711434269-d0385429813a?q=80&w=800&auto=format&fit=crop"

    except Exception as e:
        print(f"⚠️ Error crítico extrayendo imagen: {e}")
        return "https://images.unsplash.com/photo-1504711434269-d0385429813a?q=80&w=800&auto=format&fit=crop"

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
        res = requests.get(RSS_URL, timeout=10)
        root = ET.fromstring(res.content)
    except Exception as e:
        print(f"❌ Error RSS: {e}")
        return

    noticias_guardadas = cargar_noticias()
    nuevos = 0

    for item in root.findall(".//item")[:NOTICIAS_POR_CARRERA]:
        t_orig = item.find("title").text
        # Google News RSS a veces redirige, requests lo sigue automáticamente
        link = item.find("link").text if item.find("link") is not None else "#"

        if any(n.get('titulo_original') == t_orig for n in noticias_guardadas):
            continue

        print(f"🔄 Procesando: {t_orig[:60]}...")
        t_ia, r_ia, c_ia = reescribir_con_ia(t_orig)

        # AHORA LLAMAMOS A LA FUNCIÓN QUE BUSCA LA IMAGEN REAL
        img_url = obtener_imagen_real(link)

        nuevo_id = max([n["id"] for n in noticias_guardadas], default=0) + 1
        noticias_guardadas.append({
            "id": nuevo_id,
            "titulo_original": t_orig,
            "titulo": t_ia,
            "resumen": r_ia,
            "contenido": c_ia,
            "imagen": img_url,
            "fecha": datetime.today().strftime('%Y-%m-%d'),
            "url_origen": link
        })
        nuevos += 1
        print(f"✅ Guardada con imagen real: {t_ia[:50]}")

    if nuevos > 0:
        if len(noticias_guardadas) > 100:
            noticias_guardadas = noticias_guardadas[-100:]
        guardar_noticias(noticias_guardadas)
        print(f"💾 Guardadas {nuevos} noticias.")
    else:
        print("ℹ️ No hay noticias nuevas.")

if __name__ == "__main__":
    ejecutar()
