"""
Publica el personaje del día en Discord y termina (pensado para GitHub Actions).

- Elige un personaje de personajes.json que no haya salido todavía.
- Publica el embed y le agrega las reacciones 🔨 (Smash) y ❌ (Pass).
  Se vota reaccionando: no hace falta que el bot esté conectado.
- Antes de publicar el nuevo, responde al mensaje anterior con sus resultados.
- Guarda el progreso en estado.json (el workflow lo sube al repositorio).

Variables de entorno: DISCORD_TOKEN, CANAL_ID (y opcional ZONA_HORARIA, FORZAR=true).
"""
import json
import os
import random
import sys
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

API = "https://discord.com/api/v10"
TOKEN = os.getenv("DISCORD_TOKEN")
CANAL_ID = os.getenv("CANAL_ID")
ZONA = ZoneInfo(os.getenv("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))
FORZAR = os.getenv("FORZAR", "").lower() == "true"

ARCHIVO_PERSONAJES = "personajes.json"
ARCHIVO_ESTADO = "estado.json"
SMASH, PASS = "🔨", "❌"


def api(metodo, ruta, **kwargs):
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "User-Agent": "DiscordBot (smash-or-pass, 1.0)",
    }
    for _ in range(5):
        r = requests.request(metodo, f"{API}{ruta}", headers=headers, timeout=30, **kwargs)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        r.raise_for_status()
        return r.json() if r.content else None
    raise RuntimeError(f"Discord limitó el pedido a {ruta}")


def cargar_json(archivo, por_defecto):
    try:
        with open(archivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return por_defecto


def guardar_json(archivo, datos):
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)


def datos_personaje(p):
    lineas = []
    edad = p.get("edad")
    if edad:
        lineas.append(f"🎂 **Edad:** {edad} años" if isinstance(edad, int) else f"🎂 **Edad:** {edad}")
    if p.get("primera_aparicion") and p["primera_aparicion"] != "Desconocida":
        lineas.append(f"🎮 **Primera aparición:** {p['primera_aparicion']}")
    if p.get("anio"):
        lineas.append(f"📅 **Año:** {p['anio']}")
    if p.get("franquicia") and p["franquicia"] != "Desconocida":
        lineas.append(f"🏢 **Franquicia:** {p['franquicia']}")
    return lineas


def crear_embed(p, dia):
    embed = {
        "title": f"🔥 SMASH OR PASS — DÍA #{dia}",
        "description": f"## {p['nombre']}\n\n" + "\n".join(datos_personaje(p)) + "\n\n### ¿Qué opinás?",
        "color": 0x5865F2,
        "footer": {"text": f"Votá con las reacciones: {SMASH} Smash · {PASS} Pass"},
    }
    imagen = p.get("imagen")
    if imagen and imagen.startswith("https"):
        embed["image"] = {"url": imagen}
    return embed


def publicar_resultados_anteriores(estado):
    ultimo = estado.get("ultimo_mensaje")
    if not ultimo:
        return
    msg = api("GET", f"/channels/{CANAL_ID}/messages/{ultimo['id']}")
    smash = pas = 0
    for r in msg.get("reactions", []):
        n = r["count"] - (1 if r.get("me") else 0)  # no contar la reacción del bot
        if r["emoji"]["name"] == SMASH:
            smash = n
        elif r["emoji"]["name"] == PASS:
            pas = n
    total = smash + pas
    titulo = f"📊 **Resultados de {ultimo['nombre']}** (día #{ultimo['dia']})"
    if total == 0:
        texto = f"{titulo}\nNadie votó 😅"
    else:
        texto = (f"{titulo}\n"
                 f"{SMASH} **Smash:** {round(smash / total * 100)}% ({smash})\n"
                 f"{PASS} **Pass:** {round(pas / total * 100)}% ({pas})")
    api("POST", f"/channels/{CANAL_ID}/messages", json={
        "content": texto,
        "message_reference": {"message_id": ultimo["id"], "fail_if_not_exists": False},
        "allowed_mentions": {"parse": []},
    })


def main():
    if not TOKEN or not CANAL_ID:
        sys.exit("Faltan DISCORD_TOKEN o CANAL_ID")
    personajes = cargar_json(ARCHIVO_PERSONAJES, [])
    if not personajes:
        sys.exit("personajes.json está vacío o no existe")

    estado = cargar_json(ARCHIVO_ESTADO, {"dia": 0, "personajes_usados": []})
    hoy = datetime.now(ZONA).date().isoformat()
    if estado.get("ultima_fecha") == hoy and not FORZAR:
        print("Ya se publicó hoy; no hago nada.")
        return

    try:
        publicar_resultados_anteriores(estado)
    except Exception as e:  # no bloquear la publicación de hoy
        print("No pude publicar los resultados anteriores:", e)

    usados = [str(x) for x in estado.get("personajes_usados", [])]
    disponibles = [p for p in personajes if str(p["id"]) not in usados]
    if not disponibles:  # ya salieron todos: otra vuelta
        usados, disponibles = [], personajes
    p = random.choice(disponibles)
    dia = estado.get("dia", 0) + 1

    msg = api("POST", f"/channels/{CANAL_ID}/messages", json={
    "content": "<@&1557512513564975144>",
    "embeds": [crear_embed(p, dia)]
})

    # Guardar el estado apenas se publicó, antes de las reacciones
    estado["dia"] = dia
    estado["personajes_usados"] = usados + [str(p["id"])]
    estado["ultima_fecha"] = hoy
    estado["ultimo_mensaje"] = {"id": msg["id"], "nombre": p["nombre"], "dia": dia}
    guardar_json(ARCHIVO_ESTADO, estado)
    print(f"Publicado día #{dia}: {p['nombre']}")

    for emoji in (SMASH, PASS):
        api("PUT", f"/channels/{CANAL_ID}/messages/{msg['id']}/reactions/{quote(emoji)}/@me")
        time.sleep(0.7)


if __name__ == "__main__":
    main()
