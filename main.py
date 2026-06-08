import asyncio
import html
import os
import random
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


DB_PATH = Path("bot_tickets.sqlite3")
TRANSCRIPTS_DIR = Path("transcripts")
TICKET_COLOR = discord.Color.from_rgb(255, 0, 0)
MAX_TICKETS_PER_STAFF = 2

TICKET_OPTIONS = {
    "compra": ("💵", "Realizar uma compra", "Atendimento para compras, valores e formas de pagamento."),
    "suporte": ("🛡️", "Falar com o suporte", "Atendimento geral com a equipe do servidor."),
    "denuncia": ("📢", "Fazer uma denúncia", "Envie provas, nomes e detalhes da denúncia."),
    "bug": ("🐛", "Reportar bug", "Reporte erros, falhas ou problemas encontrados."),
    "parceria": ("🤝", "Fazer parceria", "Converse com a equipe sobre parcerias."),
}


def fancy(text: str) -> str:
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    styled = (
        "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
        "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
        "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
    )
    return text.translate(str.maketrans({a: b for a, b in zip(normal, styled)}))


def clean_channel_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9-]", "-", value.lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:80] or "usuario"


class Database:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.setup()

    def setup(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                staff_role_id INTEGER,
                ticket_category_id INTEGER
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                staff_id INTEGER,
                ticket_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def get_config(self, guild_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)).fetchone()
        if row:
            return dict(row)
        self.conn.execute("INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        self.conn.commit()
        return {"guild_id": guild_id, "staff_role_id": None, "ticket_category_id": None}

    def update_config(self, guild_id: int, staff_role_id: int, ticket_category_id: int) -> None:
        self.get_config(guild_id)
        self.conn.execute(
            """
            UPDATE guild_config
            SET staff_role_id = ?, ticket_category_id = ?
            WHERE guild_id = ?
            """,
            (staff_role_id, ticket_category_id, guild_id),
        )
        self.conn.commit()

    def create_ticket(self, channel_id: int, guild_id: int, owner_id: int, staff_id: int | None, ticket_type: str) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tickets
            (channel_id, guild_id, owner_id, staff_id, ticket_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (channel_id, guild_id, owner_id, staff_id, ticket_type, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_ticket(self, channel_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)).fetchone()
        return dict(row) if row else None

    def delete_ticket(self, channel_id: int) -> None:
        self.conn.execute("DELETE FROM tickets WHERE channel_id = ?", (channel_id,))
        self.conn.commit()

    def staff_open_count(self, guild_id: int, staff_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total FROM tickets WHERE guild_id = ? AND staff_id = ?",
            (guild_id, staff_id),
        ).fetchone()
        return int(row["total"])

    def count_open_tickets(self, guild_id: int) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS total FROM tickets WHERE guild_id = ?", (guild_id,)).fetchone()
        return int(row["total"])


db = Database(DB_PATH)


def can_manage_ticket(member: discord.Member, ticket: dict | None, config: dict) -> bool:
    if member.guild.owner_id == member.id:
        return True
    if ticket and ticket.get("staff_id") == member.id:
        return True
    role_id = config.get("staff_role_id")
    return bool(not ticket or not ticket.get("staff_id")) and bool(role_id and any(role.id == role_id for role in member.roles))


def choose_staff(guild: discord.Guild, role: discord.Role | None) -> discord.Member | None:
    if not role:
        return None

    members = [member for member in role.members if not member.bot]
    if not members:
        return None

    online = [member for member in members if member.status != discord.Status.offline]
    pool = online or members

    under_limit = [member for member in pool if db.staff_open_count(guild.id, member.id) < MAX_TICKETS_PER_STAFF]
    if under_limit:
        return random.choice(under_limit)

    # Se todos ja estiverem carregados, escolhe quem tem menos tickets para nao travar o atendimento.
    return min(pool, key=lambda member: db.staff_open_count(guild.id, member.id))


class TicketPanelModal(discord.ui.Modal, title="Criar painel de ticket"):
    panel_title = discord.ui.TextInput(label="Titulo", placeholder="Exemplo: DEXX TV", max_length=80)
    description = discord.ui.TextInput(
        label="Mensagem do painel",
        placeholder="Seja bem-vindo(a), facilitando o nosso atendimento...",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )
    image_url = discord.ui.TextInput(
        label="Link da imagem PNG",
        placeholder="https://site.com/banner-ticket.png",
        max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not str(self.image_url).lower().split("?")[0].endswith(".png"):
            await interaction.response.send_message(fancy("O link da imagem precisa terminar com .png."), ephemeral=True)
            return

        embed = discord.Embed(
            title=fancy(str(self.panel_title)),
            description=fancy(str(self.description)),
            color=TICKET_COLOR,
        )
        embed.set_image(url=str(self.image_url))
        embed.set_footer(text="Selecione uma opcao abaixo para iniciar seu atendimento.")
        await interaction.channel.send(embed=embed, view=TicketSelectView())
        await interaction.response.send_message(fancy("Painel de ticket enviado com sucesso."), ephemeral=True)


class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=value, emoji=emoji, description=description)
            for value, (emoji, label, description) in TICKET_OPTIONS.items()
        ]
        super().__init__(placeholder="Selecione uma opcao...", options=options, custom_id="ticket_select")

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        config = db.get_config(guild.id)
        staff_role = guild.get_role(config.get("staff_role_id") or 0)
        category = guild.get_channel(config.get("ticket_category_id") or 0)
        assigned_staff = choose_staff(guild, staff_role)

        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(fancy("Configure a categoria de tickets usando /ticket_config."), ephemeral=True)
            return

        selected = self.values[0]
        emoji, label, _ = TICKET_OPTIONS[selected]
        channel_name = f"ticket-{selected}-{clean_channel_name(member.name)}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        if assigned_staff:
            overwrites[assigned_staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        elif staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites, reason="Ticket criado")
        db.create_ticket(channel.id, guild.id, member.id, assigned_staff.id if assigned_staff else None, selected)

        staff_line = assigned_staff.mention if assigned_staff else "Nenhum staff disponivel foi encontrado. A equipe sera chamada pelo cargo."
        content = f"{member.mention} {assigned_staff.mention if assigned_staff else staff_role.mention if staff_role else ''}".strip()
        embed = discord.Embed(
            title=fancy(f"{emoji} Ticket aberto"),
            description=(
                f"{fancy('Categoria')}: **{label}**\n"
                f"{fancy('Usuario')}: {member.mention}\n"
                f"{fancy('Staff selecionado')}: {staff_line}\n\n"
                f"{fancy('Explique seu problema com detalhes. Apenas voce e o staff selecionado conseguem ver este ticket.')}"
            ),
            color=TICKET_COLOR,
        )
        embed.set_footer(text="O botao de fechar fica visivel para todos, mas so o staff selecionado ou o dono do servidor pode fechar.")
        await channel.send(content=content, embed=embed, view=TicketControlView())
        await interaction.response.send_message(fancy(f"Ticket criado: {channel.mention}"), ephemeral=True)


class TicketSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fechar Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = db.get_ticket(interaction.channel.id)
        config = db.get_config(interaction.guild_id)
        if not can_manage_ticket(interaction.user, ticket, config):
            await interaction.response.send_message(fancy("Voce nao tem permissao para fechar este ticket."), ephemeral=True)
            return

        await interaction.response.send_message(fancy("Ticket fechado. O canal sera apagado em 5 segundos."), ephemeral=True)
        db.delete_ticket(interaction.channel.id)
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket fechado por {interaction.user}")

    @discord.ui.button(label="Gerar Transcript", emoji="📄", style=discord.ButtonStyle.secondary, custom_id="ticket_transcript")
    async def transcript_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = db.get_ticket(interaction.channel.id)
        config = db.get_config(interaction.guild_id)
        if not can_manage_ticket(interaction.user, ticket, config):
            await interaction.response.send_message(fancy("Voce nao tem permissao para gerar transcript."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        transcript = await create_transcript(interaction.channel)
        await interaction.followup.send(file=discord.File(transcript), ephemeral=True)


async def create_transcript(channel: discord.TextChannel) -> Path:
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    messages = [message async for message in channel.history(limit=None, oldest_first=True)]
    path = TRANSCRIPTS_DIR / f"transcript-{channel.id}.html"
    rows = []
    for message in messages:
        author = html.escape(str(message.author))
        content = html.escape(message.content or "")
        created = message.created_at.strftime("%d/%m/%Y %H:%M")
        attachments = " ".join(html.escape(attachment.url) for attachment in message.attachments)
        rows.append(f"<article><b>{author}</b> <small>{created}</small><p>{content}</p><p>{attachments}</p></article>")

    path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Transcript</title>"
        "<style>body{font-family:Arial;background:#111;color:#eee;padding:24px}"
        "article{border-bottom:1px solid #333;padding:12px 0}small{color:#aaa}</style></head><body>"
        f"<h1>{html.escape(channel.name)}</h1>{''.join(rows)}</body></html>",
        encoding="utf-8",
    )
    return path


class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        self.add_view(TicketSelectView())
        self.add_view(TicketControlView())
        await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"Bot conectado como {self.user} | {len(self.guilds)} servidor(es)")

    async def on_member_join(self, member: discord.Member) -> None:
        channel = member.guild.system_channel
        if not channel or not channel.permissions_for(member.guild.me).send_messages:
            return
        embed = discord.Embed(
            title=fancy("Seja bem-vindo(a)!"),
            description=fancy(f"{member.mention}, esperamos que voce tenha uma otima experiencia no servidor."),
            color=TICKET_COLOR,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)


bot = TicketBot()


async def save_ticket_config(interaction: discord.Interaction, cargo_staff: discord.Role, categoria_tickets: discord.CategoryChannel) -> None:
    db.update_config(interaction.guild_id, cargo_staff.id, categoria_tickets.id)
    await interaction.response.send_message(
        fancy(f"Configuracao salva.\nStaff: {cargo_staff.name}\nCategoria: {categoria_tickets.name}"),
        ephemeral=True,
    )


@bot.tree.command(name="ticket", description="Abre o modal para criar um painel profissional de tickets.")
@app_commands.checks.has_permissions(administrator=True)
async def ticket(interaction: discord.Interaction):
    await interaction.response.send_modal(TicketPanelModal())


@bot.tree.command(name="ticket_config", description="Configura apenas cargo staff e categoria dos tickets.")
@app_commands.describe(
    cargo_staff="Cargo que vai responder tickets.",
    categoria_tickets="Categoria onde os tickets serao criados.",
)
@app_commands.checks.has_permissions(administrator=True)
async def ticket_config(interaction: discord.Interaction, cargo_staff: discord.Role, categoria_tickets: discord.CategoryChannel):
    await save_ticket_config(interaction, cargo_staff, categoria_tickets)


@bot.tree.command(name="configurar", description="Atalho para configurar cargo staff e categoria dos tickets.")
@app_commands.describe(
    cargo_staff="Cargo que vai responder tickets.",
    categoria_tickets="Categoria onde os tickets serao criados.",
)
@app_commands.checks.has_permissions(administrator=True)
async def configurar(interaction: discord.Interaction, cargo_staff: discord.Role, categoria_tickets: discord.CategoryChannel):
    await save_ticket_config(interaction, cargo_staff, categoria_tickets)


@bot.tree.command(name="ticket_info", description="Mostra informacoes do ticket atual.")
async def ticket_info(interaction: discord.Interaction):
    ticket_data = db.get_ticket(interaction.channel_id)
    if not ticket_data:
        await interaction.response.send_message(fancy("Este canal nao parece ser um ticket."), ephemeral=True)
        return

    emoji, label, _ = TICKET_OPTIONS.get(ticket_data["ticket_type"], ("🎫", ticket_data["ticket_type"], ""))
    staff = f"<@{ticket_data['staff_id']}>" if ticket_data.get("staff_id") else "Sem staff fixo"
    embed = discord.Embed(
        title=fancy(f"{emoji} Informacoes do ticket"),
        description=(
            f"**Dono:** <@{ticket_data['owner_id']}>\n"
            f"**Staff:** {staff}\n"
            f"**Tipo:** {label}\n"
            f"**Criado em:** {ticket_data['created_at']}"
        ),
        color=TICKET_COLOR,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="ticket_renomear", description="Renomeia o ticket atual.")
async def ticket_renomear(interaction: discord.Interaction, nome: str):
    ticket_data = db.get_ticket(interaction.channel_id)
    config = db.get_config(interaction.guild_id)
    if not can_manage_ticket(interaction.user, ticket_data, config):
        await interaction.response.send_message(fancy("Voce nao tem permissao para renomear este ticket."), ephemeral=True)
        return
    await interaction.channel.edit(name=clean_channel_name(nome), reason=f"Ticket renomeado por {interaction.user}")
    await interaction.response.send_message(fancy("Ticket renomeado com sucesso."), ephemeral=True)


@bot.tree.command(name="ticket_transcript", description="Gera o transcript do ticket atual apenas para voce.")
async def ticket_transcript(interaction: discord.Interaction):
    ticket_data = db.get_ticket(interaction.channel_id)
    config = db.get_config(interaction.guild_id)
    if not can_manage_ticket(interaction.user, ticket_data, config):
        await interaction.response.send_message(fancy("Voce nao tem permissao para gerar transcript."), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    transcript = await create_transcript(interaction.channel)
    await interaction.followup.send(file=discord.File(transcript), ephemeral=True)


@bot.tree.command(name="anuncio", description="Envia um anuncio profissional em embed.")
@app_commands.checks.has_permissions(administrator=True)
async def anuncio(interaction: discord.Interaction, titulo: str, mensagem: str):
    embed = discord.Embed(title=fancy(titulo), description=fancy(mensagem), color=TICKET_COLOR)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="embed", description="Envia uma mensagem em embed com imagem PNG opcional.")
@app_commands.checks.has_permissions(administrator=True)
async def embed(interaction: discord.Interaction, titulo: str, mensagem: str, imagem_png: str | None = None):
    if imagem_png and not imagem_png.lower().split("?")[0].endswith(".png"):
        await interaction.response.send_message(fancy("A imagem precisa ser um link .png."), ephemeral=True)
        return
    embed_message = discord.Embed(title=fancy(titulo), description=fancy(mensagem), color=TICKET_COLOR)
    if imagem_png:
        embed_message.set_image(url=imagem_png)
    await interaction.response.send_message(embed=embed_message)


@bot.tree.command(name="say", description="Faz o bot enviar uma mensagem normal estilizada.")
@app_commands.checks.has_permissions(administrator=True)
async def say(interaction: discord.Interaction, mensagem: str):
    await interaction.response.send_message(fancy("Mensagem enviada."), ephemeral=True)
    await interaction.channel.send(fancy(mensagem))


@bot.tree.command(name="limpar", description="Limpa mensagens do canal atual.")
@app_commands.checks.has_permissions(manage_messages=True)
async def limpar(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=quantidade)
    await interaction.followup.send(fancy(f"{len(deleted)} mensagens apagadas."), ephemeral=True)


@bot.tree.command(name="config_ver", description="Mostra a configuracao atual do ticket.")
@app_commands.checks.has_permissions(administrator=True)
async def config_ver(interaction: discord.Interaction):
    config = db.get_config(interaction.guild_id)
    staff = f"<@&{config.get('staff_role_id')}>" if config.get("staff_role_id") else "Nao configurado"
    category = f"<#{config.get('ticket_category_id')}>" if config.get("ticket_category_id") else "Nao configurada"
    embed = discord.Embed(
        title=fancy("Configuracao atual"),
        description=f"**Staff:** {staff}\n**Categoria dos tickets:** {category}",
        color=TICKET_COLOR,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="boasvindas_testar", description="Testa a mensagem de boas-vindas no canal atual.")
@app_commands.checks.has_permissions(administrator=True)
async def boasvindas_testar(interaction: discord.Interaction):
    embed = discord.Embed(
        title=fancy("Seja bem-vindo(a)!"),
        description=fancy(f"{interaction.user.mention}, esperamos que voce tenha uma otima experiencia no servidor."),
        color=TICKET_COLOR,
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="staff_ping", description="Chama o cargo staff configurado.")
async def staff_ping(interaction: discord.Interaction, motivo: str):
    config = db.get_config(interaction.guild_id)
    role_id = config.get("staff_role_id")
    if not role_id:
        await interaction.response.send_message(fancy("Nenhum cargo staff foi configurado ainda."), ephemeral=True)
        return
    await interaction.response.send_message(f"<@&{role_id}> {fancy('Solicitacao de atendimento:')} {motivo}")


@bot.tree.command(name="ajuda", description="Mostra os comandos principais do bot.")
async def ajuda(interaction: discord.Interaction):
    commands_text = "\n".join(
        [
            "/ticket - criar painel de ticket por modal",
            "/ticket_config - configurar cargo staff e categoria",
            "/configurar - atalho do ticket_config",
            "/ticket_info - ver dados do ticket",
            "/ticket_renomear - renomear ticket",
            "/ticket_transcript - gerar transcript so para voce",
            "/anuncio - enviar anuncio",
            "/embed - enviar embed com imagem PNG",
            "/say - mensagem normal estilizada",
            "/limpar - apagar mensagens",
            "/config_ver - ver configuracao",
            "/boasvindas_testar - testar entrada",
            "/staff_ping - chamar staff",
            "/status - status geral",
        ]
    )
    embed = discord.Embed(title=fancy("Central de ajuda"), description=commands_text, color=TICKET_COLOR)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="status", description="Mostra informacoes do bot.")
async def status(interaction: discord.Interaction):
    total = db.count_open_tickets(interaction.guild_id)
    embed = discord.Embed(
        title=fancy("Status do bot"),
        description=fancy(f"Tickets abertos: {total}\nPing: {round(bot.latency * 1000)}ms\nServidores: {len(bot.guilds)}"),
        color=TICKET_COLOR,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@ticket.error
@ticket_config.error
@configurar.error
@anuncio.error
@embed.error
@say.error
@limpar.error
@config_ver.error
@boasvindas_testar.error
async def permission_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(fancy("Voce nao tem permissao para usar este comando."), ephemeral=True)
    else:
        raise error


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token or token == "COLOQUE_SEU_TOKEN_AQUI":
        raise RuntimeError("Coloque o token do bot no arquivo .env em DISCORD_TOKEN.")
    bot.run(token)


if __name__ == "__main__":
    main()
