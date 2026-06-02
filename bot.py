import os
import json
import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime

RSS_URL = "https://news.google.com/rss/search?q=when:1d+geo:Mexico&hl=es-419&gl=MX&ceid=MX:es-419"
JSON_PATH = "data/noticias.json"

# CREDENCIALES (Jaladas desde GitHub Secrets de forma segura)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
GITHUB_USERNAME = "daniel00998888"

def cargar_noticias():
    if not os.path.exists(JSON_PATH): return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return []

def guardar_noticias(noticias):
    # Asegurarnos de que la carpeta 'data' exista antes de guardar
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)

def limpiar_html(texto):
    """Elimina las etiquetas HTML basura del RSS."""
    if not texto: return ""
    return re.sub(r'<[^>]+>', '', texto).strip()

def extraer_imagen_original(texto_html):
    """Extrae la URL de la miniatura original de la noticia si existe."""
    if not texto_html: return None
    match = re.search(r'<img[^>]+src="([^">]+)"', texto_html)
    return match.group(1) if match else None

def reescribir_con_ia(titulo_orig, resumen_orig):
    if not GROQ_API_KEY: return titulo_orig, resumen_orig, resumen_orig
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""
    Actúa como un periodista digital mexicano enfocado en tráfico viral. Reescribe esta noticia.
    Devuelve ESTRICTAMENTE un objeto JSON. No agregues comillas invertidas (```json) ni texto adicional.
    Estructura exacta:
    {{
      "titulo": "Titular muy llamativo y clickbait ético",
      "resumen": "Un gancho corto de 2 líneas para redes sociales",
      "contenido": "Desarrollo completo de la noticia en 3 párrafos amplios y profesionales."
    }}
    
    Noticia original: {titulo_orig} - {resumen_orig}
    """
    payload = {
        "model": "llama3-70b-8192", # Modelo más potente para respetar el JSON
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.5
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20).json()
        contenido_crudo = res['choices'][0]['message']['content']
        
        # 🔥 CORRECCIÓN: Quitamos los bloques de código usando Regex para evitar fallos de sintaxis
        contenido_limpio = re.sub(r'```[a-z]*', '', contenido_crudo).strip()
        data = json.loads(contenido_limpio)
        
        return data.get("titulo", titulo_orig), data.get("resumen", resumen_orig), data.get("contenido", resumen_orig)
    except Exception as e:
        print(f"⚠️ Error al procesar con IA: {e}")
        return titulo_orig, resumen_orig, resumen_orig

def publicar_en_facebook(titulo, resumen, id_noticia, imagen_url):
    if not FB_PAGE_ID or not FB_ACCESS_TOKEN:
        print("⚠️ Configuración de Facebook incompleta. Saltando posteo.")
        return
    
    url_web = f"https://{GITHUB_USERNAME}.github.io/pulsomx/noticia.html?id={id_noticia}"
    mensaje = f"🚨 {titulo} 🚨\n\n{resumen}\n\n👉 Enterate de todos los detalles aquí: {url_web}"
    
    fb_url = f"[https://graph.facebook.com/v20.0/](https://graph.facebook.com/v20.0/){FB_PAGE_ID}/photos"
    payload = {"url": imagen_url, "caption": mensaje, "access_token": FB_ACCESS_TOKEN}
    try:
        r = requests.post(fb_url, data=payload, timeout=15)
        if r.status_code == 200: print("📢 ¡Publicado en FB con éxito!")
        else: print(f"❌ Error FB: {r.text}")
    except Exception as e:
        print(f"❌ Fallo de conexión Meta API: {e}")

def ejecutar():
    print("Buscando noticias en México...")
    try:
        res = requests.get(RSS_URL, timeout=10)
        if res.status_code != 200: return
    except Exception as e:
        print(f"❌ Error conectando a Google News: {e}")
        return
    
    root = ET.fromstring(res.content)
    noticias_guardadas = cargar_noticias()
    titulos_viejos = {n["titulo_original"] for n in noticias_guardadas if "titulo_original" in n}
    
    nuevos = 0
    # Procesamos 2 noticias por ejecución para no exceder cuotas
    for item in root.findall(".//item")[:2]: 
        t_orig = item.find("title").text
        link = item.find("link").text
        desc_html = item.find("description").text or ""
        
        if t_orig in titulos_viejos: continue
        
        desc_limpia = limpiar_html(desc_html)
        t_ia, r_ia, c_ia = reescribir_con_ia(t_orig, desc_limpia)
        
        # 1. Intentamos obtener la imagen real
        img_url = extraer_imagen_original(desc_html)
        
        # 2. Si no existe, creamos una muy realista
        if not img_url:
            texto_seguro = re.sub(r'[^a-zA-Z0-9 ]', '', t_ia[:50])
            prompt_img = requests.utils.quote(f"photojournalism, documentary news photography, highly realistic, 8k resolution, {texto_seguro}")
            img_url = f"[https://image.pollinations.ai/prompt/](https://image.pollinations.ai/prompt/){prompt_img}?width=800&height=500&nologo=true"
        
        nuevo_id = max([n["id"] for n in noticias_guardadas], default=0) + 1
        
        noticias_guardadas.append({
            "id": nuevo_id, "titulo_original": t_orig, "titulo": t_ia,
            "resumen": r_ia, "contenido": c_ia, "imagen": img_url,
            "fecha": datetime.today().strftime('%Y-%m-%d'), "url_origen": link
        })
        nuevos += 1
        print(f"✅ Procesada: {t_ia[:40]}...")
        
        publicar_en_facebook(t_ia, r_ia, nuevo_id, img_url)
        
    if nuevos > 0:
        guardar_noticias(noticias_guardadas)
        print("💾 JSON actualizado de forma local.")

if __name__ == "__main__":
    ejecutar()
