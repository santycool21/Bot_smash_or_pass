import os
import json
import random
from datetime import time
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # Opcional: ID de tu servidor para que los comandos aparezcan al instante

if not TOKEN:
    raise ValueError("No se encontró DISCORD_TOKEN en el archivo .env")

# Publicación diaria automática (todo se configura en el .env)
CANAL_ID = os.getenv("CANAL_ID")  # ID del canal donde se publica cada día
HORA_PUBLICACION = os.getenv("HORA_PUBLICACION", "12:00")  # formato HH:MM
ZONA_HORARIA = os.getenv("ZONA_HORARIA", "America/Argentina/Buenos_Aires")

_hora, _minuto = HORA_PUBLICACION.split(":")
HORA = time(int(_hora), int(_minuto), tzinfo=ZoneInfo(ZONA_HORARIA))

ARCHIVO_PERSONAJES = "personajes.json"
ARCHIVO_VOTOS = "votos.json"
ARCHIVO_ESTADO = "estado.json"


# =========================
# FUNCIONES JSON
# =========================

def cargar_json(archivo, valor_por_defecto):
    try:
        with open(archivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return valor_por_defecto


def guardar_json(archivo, datos):
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)


def cargar_personajes():
    return cargar_json(ARCHIVO_PERSONAJES, [])


def buscar_personaje_por_id(personaje_id):
    for p in cargar_personajes():
        if str(p["id"]) == str(personaje_id):
            return p
    return None


# =========================
# VOTOS
# =========================

async def registrar_voto(interaction: discord.Interaction, personaje_id: str, voto: str):
    try:
        votos = cargar_json(ARCHIVO_VOTOS, {})
        datos = votos.setdefault(personaje_id, {"smash": [], "pass": []})
        usuario_id = str(interaction.user.id)

        if usuario_id in datos["smash"] or usuario_id in datos["pass"]:
            await interaction.response.send_message(
                "Ya votaste por este personaje 😏", ephemeral=True
            )
            return

        datos[voto].append(usuario_id)
        guardar_json(ARCHIVO_VOTOS, votos)

        smash = len(datos["smash"])
        pas = len(datos["pass"])
        total = smash + pas

        await interaction.response.send_message(
            f"Voto registrado 😎\n\n"
            f"🔨 **Smash:** {round(smash / total * 100)}% ({smash})\n"
            f"❌ **Pass:** {round(pas / total * 100)}% ({pas})",
            ephemeral=True,
        )

    except Exception as e:
        print("ERROR AL REGISTRAR VOTO:", e)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Ocurrió un error al registrar tu voto.", ephemeral=True
            )


# =========================
# BOTONES (siguen funcionando aunque reinicies el bot)
# =========================

class VotoButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"sop:(?P<voto>smash|pass):(?P<pid>\d+)",
):
    def __init__(self, voto: str, personaje_id: str):
        es_smash = voto == "smash"
        super().__init__(
            discord.ui.Button(
                label="Smash" if es_smash else "Pass",
                emoji="🔨" if es_smash else "❌",
                style=discord.ButtonStyle.green if es_smash else discord.ButtonStyle.red,
                custom_id=f"sop:{voto}:{personaje_id}",
            )
        )
        self.voto = voto
        self.personaje_id = str(personaje_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["voto"], match["pid"])

    async def callback(self, interaction: discord.Interaction):
        await registrar_voto(interaction, self.personaje_id, self.voto)


def crear_view(personaje):
    view = discord.ui.View(timeout=None)
    view.add_item(VotoButton("smash", personaje["id"]))
    view.add_item(VotoButton("pass", personaje["id"]))
    return view


# =========================
# EMBEDS
# =========================

def datos_personaje(personaje):
    """Arma las líneas de info. Los campos que falten simplemente no se muestran."""
    lineas = []

    edad = personaje.get("edad")
    if edad:
        texto_edad = f"{edad} años" if isinstance(edad, int) else str(edad)
        lineas.append(f"🎂 **Edad:** {texto_edad}")

    if personaje.get("primera_aparicion") and personaje["primera_aparicion"] != "Desconocida":
        lineas.append(f"🎮 **Primera aparición:** {personaje['primera_aparicion']}")

    if personaje.get("anio"):
        lineas.append(f"📅 **Año:** {personaje['anio']}")

    if personaje.get("franquicia") and personaje["franquicia"] != "Desconocida":
        lineas.append(f"🏢 **Franquicia:** {personaje['franquicia']}")

    return lineas


def crear_embed(personaje, numero_dia):
    lineas = datos_personaje(personaje)

    descripcion = f"## {personaje['nombre']}\n\n" + "\n".join(lineas) + "\n\n### ¿Qué opinás?"

    embed = discord.Embed(
        title=f"🔥 SMASH OR PASS — DÍA #{numero_dia}",
        description=descripcion,
        color=discord.Color.blurple(),
    )

    imagen = personaje.get("imagen")
    if imagen and imagen.startswith("https"):
        embed.set_image(url=imagen)

    embed.set_footer(text="Solo podés votar una vez por personaje.")
    return embed


# =========================
# PERSONAJE DEL DÍA
# =========================

def obtener_personaje_del_dia():
    personajes = cargar_personajes()
    estado = cargar_json(ARCHIVO_ESTADO, {"dia": 0, "personajes_usados": []})

    if not personajes:
        return None, estado

    usados = [str(x) for x in estado.get("personajes_usados", [])]
    disponibles = [p for p in personajes if str(p["id"]) not in usados]

    if not disponibles:  # ya salieron todos: empezamos otra vuelta
        usados = []
        disponibles = personajes

    personaje = random.choice(disponibles)

    estado["dia"] = estado.get("dia", 0) + 1
    estado["personajes_usados"] = usados + [str(personaje["id"])]
    guardar_json(ARCHIVO_ESTADO, estado)

    return personaje, estado


async def publicar_personaje_diario(canal):
    personaje, estado = obtener_personaje_del_dia()

    if personaje is None:
        print("No hay personajes disponibles.")
        return

    await canal.send(
        embed=crear_embed(personaje, estado["dia"]),
        view=crear_view(personaje),
    )
    print(f"Personaje del día publicado: {personaje['nombre']}")


# =========================
# BOT
# =========================

class SmashBot(commands.Bot):
    async def setup_hook(self):
        # Registra los botones para que funcionen después de reiniciar el bot
        self.add_dynamic_items(VotoButton)

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()

        print(f"Comandos sincronizados: {len(synced)}")

        if CANAL_ID:
            if not publicacion_diaria.is_running():
                publicacion_diaria.start()
            print(f"Publicación diaria programada a las {HORA_PUBLICACION} ({ZONA_HORARIA})")
        else:
            print("CANAL_ID no está en el .env: no habrá publicación diaria automática.")


bot = SmashBot(command_prefix="!", intents=discord.Intents.default())


# =========================
# PUBLICACIÓN DIARIA AUTOMÁTICA
# =========================

@tasks.loop(time=HORA)
async def publicacion_diaria():
    try:
        canal = bot.get_channel(int(CANAL_ID)) or await bot.fetch_channel(int(CANAL_ID))
        await publicar_personaje_diario(canal)
    except Exception as e:
        print("ERROR EN LA PUBLICACIÓN DIARIA:", e)


@publicacion_diaria.before_loop
async def antes_de_publicar():
    await bot.wait_until_ready()


@bot.tree.command(
    name="publicar_hoy",
    description="(Admin) Publica ahora el personaje del día en este canal.",
)
@app_commands.default_permissions(administrator=True)
async def publicar_hoy(interaction: discord.Interaction):
    await interaction.response.send_message("✅ Publicando...", ephemeral=True)
    await publicar_personaje_diario(interaction.channel)


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


# =========================
# /smashorpass
# =========================

@bot.tree.command(name="smashorpass", description="Publica un personaje aleatorio.")
async def smashorpass(interaction: discord.Interaction):
    personajes = cargar_personajes()

    if not personajes:
        await interaction.response.send_message(
            "❌ No hay personajes en personajes.json.", ephemeral=True
        )
        return

    personaje = random.choice(personajes)

    await interaction.response.send_message(
        embed=crear_embed(personaje, "PRUEBA"),
        view=crear_view(personaje),
    )


# =========================
# /resultados
# =========================

async def autocompletar_personajes(interaction: discord.Interaction, texto: str):
    texto = texto.lower()
    nombres = [p["nombre"] for p in cargar_personajes() if texto in p["nombre"].lower()]
    return [app_commands.Choice(name=n, value=n) for n in nombres[:25]]


@bot.tree.command(name="resultados", description="Muestra los resultados de un personaje.")
@app_commands.describe(personaje="Nombre del personaje")
@app_commands.autocomplete(personaje=autocompletar_personajes)
async def resultados(interaction: discord.Interaction, personaje: str):
    encontrado = next(
        (p for p in cargar_personajes() if p["nombre"].lower() == personaje.lower()),
        None,
    )

    if encontrado is None:
        await interaction.response.send_message("❌ No encontré ese personaje.", ephemeral=True)
        return

    votos = cargar_json(ARCHIVO_VOTOS, {})
    datos = votos.get(str(encontrado["id"]), {"smash": [], "pass": []})

    smash = len(datos["smash"])
    pas = len(datos["pass"])
    total = smash + pas

    if total == 0:
        await interaction.response.send_message(
            f"📊 **{encontrado['nombre']}** todavía no tiene votos."
        )
        return

    lineas = datos_personaje(encontrado)
    lineas.append("")
    lineas.append(f"🔨 **Smash:** {round(smash / total * 100)}% ({smash})")
    lineas.append(f"❌ **Pass:** {round(pas / total * 100)}% ({pas})")
    lineas.append("")
    lineas.append(f"👥 **Total de votos:** {total}")

    embed = discord.Embed(
        title=f"📊 Resultados — {encontrado['nombre']}",
        description="\n".join(lineas),
        color=discord.Color.blurple(),
    )

    imagen = encontrado.get("imagen")
    if imagen and imagen.startswith("https"):
        embed.set_thumbnail(url=imagen)

    await interaction.response.send_message(embed=embed)


# =========================
# INICIAR
# =========================

bot.run(TOKEN)
