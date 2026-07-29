"""Installable, multi-server Discord app for Transport Victoria disruptions."""
from __future__ import annotations
import asyncio, logging, os, sqlite3
from pathlib import Path
from typing import Any
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from bot import fetch_disruptions, make_embed, normalize_route_name, require_env

DATA_FILE = Path(os.getenv("DATA_FILE", Path(__file__).with_name("discord_app.db")))
VALID_ROUTES = (
    "Alamein", "Belgrave", "Craigieburn", "Cranbourne", "Flemington Racecourse",
    "Frankston", "Glen Waverley", "Hurstbridge", "Lilydale", "Mernda",
    "Pakenham", "Sandringham", "Stony Point", "Sunbury", "Upfield",
    "Werribee", "Williamstown", "tram", "vline",
)
VALID_ROUTE_KEYS = {normalize_route_name(route) for route in VALID_ROUTES}

class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS guilds(guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS roles(guild_id INTEGER NOT NULL, route_key TEXT NOT NULL, role_id INTEGER NOT NULL, PRIMARY KEY(guild_id, route_key));
        CREATE TABLE IF NOT EXISTS seen(guild_id INTEGER NOT NULL, disruption_id INTEGER NOT NULL, PRIMARY KEY(guild_id, disruption_id));
        """)
    def configure(self, guild_id, channel_id):
        self.db.execute("INSERT INTO guilds VALUES(?,?,1) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,enabled=1", (guild_id, channel_id)); self.db.commit()
    def disable(self, guild_id):
        self.db.execute("UPDATE guilds SET enabled=0 WHERE guild_id=?", (guild_id,)); self.db.commit()
    def guild(self, guild_id):
        return self.db.execute("SELECT channel_id,enabled FROM guilds WHERE guild_id=?", (guild_id,)).fetchone()
    def enabled_guilds(self):
        return self.db.execute("SELECT guild_id,channel_id FROM guilds WHERE enabled=1").fetchall()
    def set_role(self, guild_id, key, role_id):
        self.db.execute("INSERT INTO roles VALUES(?,?,?) ON CONFLICT(guild_id,route_key) DO UPDATE SET role_id=excluded.role_id", (guild_id,key,role_id)); self.db.commit()
    def remove_role(self, guild_id, key):
        cur=self.db.execute("DELETE FROM roles WHERE guild_id=? AND route_key=?",(guild_id,key)); self.db.commit(); return cur.rowcount > 0
    def roles(self, guild_id):
        return dict(self.db.execute("SELECT route_key,role_id FROM roles WHERE guild_id=?",(guild_id,)).fetchall())
    def has_seen(self, guild_id, disruption_id):
        return self.db.execute("SELECT 1 FROM seen WHERE guild_id=? AND disruption_id=?",(guild_id,disruption_id)).fetchone() is not None
    def mark_seen(self, guild_id, disruption_id):
        self.db.execute("INSERT OR IGNORE INTO seen VALUES(?,?)",(guild_id,disruption_id)); self.db.commit()

def route_keys(disruption: dict[str, Any]):
    keys=[]; mode=disruption.get("_ptv_mode")
    if mode == "metro_tram": keys.append("tram")
    elif mode == "regional_train": keys.append("vline")
    for route in disruption.get("routes") or []:
        if isinstance(route,dict):
            key=normalize_route_name(route.get("route_name"))
            if key and key not in keys: keys.append(key)
    return keys

def config_key(route):
    key=normalize_route_name(route)
    if key in {"trams","metro tram"}: return "tram"
    if key in {"v/line","v line","regional","regional train"}: return "vline"
    return key

class PTVApp(commands.Bot):
    def __init__(self, dev_id, api_key, store):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.dev_id,self.api_key,self.store=dev_id,api_key,store
    async def setup_hook(self):
        await self.tree.sync(); self.poll.start()
    async def on_ready(self): logging.info("Signed in as %s", self.user)
    @tasks.loop(minutes=5)
    async def poll(self):
        try: disruptions=await asyncio.to_thread(fetch_disruptions,self.dev_id,self.api_key)
        except Exception: logging.exception("PTV poll failed"); return
        for guild_id,channel_id in self.store.enabled_guilds():
            channel=self.get_channel(channel_id)
            if not isinstance(channel,discord.TextChannel): continue
            configured=self.store.roles(guild_id)
            for disruption in disruptions:
                try: disruption_id=int(disruption["disruption_id"])
                except (KeyError,TypeError,ValueError): continue
                if self.store.has_seen(guild_id,disruption_id): continue
                role_ids=list(dict.fromkeys(configured[k] for k in route_keys(disruption) if k in configured))
                try:
                    await channel.send(content=" ".join(f"<@&{r}>" for r in role_ids) or None,embed=discord.Embed.from_dict(make_embed(disruption)),allowed_mentions=discord.AllowedMentions(everyone=False,users=False,roles=[discord.Object(id=r) for r in role_ids]))
                except discord.HTTPException: logging.exception("Post failed for guild %s",guild_id); continue
                self.store.mark_seen(guild_id,disruption_id)
    @poll.before_loop
    async def before_poll(self): await self.wait_until_ready()

async def route_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    query = current.casefold().strip()
    return [
        app_commands.Choice(name=route, value=route)
        for route in VALID_ROUTES
        if query in route.casefold()
    ][:25]


def install_commands(app):
    @app.tree.command(description="Choose the channel for PTV disruption alerts.")
    @app_commands.default_permissions(manage_guild=True)
    async def setup(interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        disruptions = await asyncio.to_thread(fetch_disruptions, app.dev_id, app.api_key)
        for disruption in disruptions:
            try:
                app.store.mark_seen(interaction.guild_id, int(disruption["disruption_id"]))
            except (KeyError, TypeError, ValueError):
                pass
        app.store.configure(interaction.guild_id, channel.id)
        await interaction.followup.send(f"Alerts enabled in {channel.mention}. New disruptions will be posted from now on.", ephemeral=True)
    @app.tree.command(description="Assign a mention role to a route, tram, or V/Line.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.autocomplete(route=route_autocomplete)
    async def set_role(interaction: discord.Interaction, route: str, role: discord.Role):
        key = config_key(route)
        if key not in VALID_ROUTE_KEYS:
            await interaction.response.send_message("Choose a valid route from the suggestions.", ephemeral=True)
            return
        app.store.set_role(interaction.guild_id, key, role.id)
        await interaction.response.send_message(f"{role.mention} assigned to {route}.", ephemeral=True)
    @app.tree.command(description="Remove a route mention role.")
    @app_commands.default_permissions(manage_guild=True)
    async def remove_role(interaction: discord.Interaction, route: str):
        key=config_key(route); removed=app.store.remove_role(interaction.guild_id,key); await interaction.response.send_message("Role mapping removed." if removed else "No mapping found.",ephemeral=True)
    @app.tree.command(description="Show this server's alert configuration.")
    async def status(interaction: discord.Interaction):
        cfg=app.store.guild(interaction.guild_id); roles=app.store.roles(interaction.guild_id)
        message="Not configured. A server manager can run /setup." if not cfg else f"Alerts: {'enabled' if cfg[1] else 'disabled'}\nChannel: <#{cfg[0]}>\nRoles: "+(", ".join(f"{k} -> <@&{v}>" for k,v in roles.items()) or "none")
        await interaction.response.send_message(message,ephemeral=True)
    @app.tree.command(description="Stop PTV alerts in this server.")
    @app_commands.default_permissions(manage_guild=True)
    async def disable(interaction: discord.Interaction):
        app.store.disable(interaction.guild_id); await interaction.response.send_message("PTV alerts disabled.",ephemeral=True)

def main():
    load_dotenv(); logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    app=PTVApp(require_env("PTV_DEV_ID"),require_env("PTV_API_KEY"),Store(DATA_FILE)); install_commands(app); app.run(require_env("DISCORD_BOT_TOKEN"),log_handler=None)
if __name__ == "__main__": main()