# System imports
import math
import os
import random
import re
import asyncio

# First party imports
from .errors import *
from .utils import *

# Third-party imports
import discord
from discord import app_commands
import youtube_dl
import lavalink
from dotenv import load_dotenv

# Setup pattern to match against urls
url_rx = re.compile(r'https?://(?:www\.)?.+')

# Load environment variables and set them
load_dotenv(".env")
token = os.getenv("DISCORD_TOKEN")
guild_id = discord.Object(id=os.getenv("GUILD_ID"))

embed_color = discord.Color(0xEB4E2F)
inactive_timeout = 60 # in seconds

class LavalinkVoiceClient(discord.VoiceClient):
    """Voice client that connects Lavalink events to Discord.py voice client

    Attributes
    ----------
    client : discord.Client
        The client/bot instance
    channel : discord.abc.Connectable
        The channel to connect to
    """
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable) -> None:
        self.client = client
        self.channel = channel

        if hasattr(self.client, "lavalink"):
            self.lavalink = self.client.lavalink
        else:
            self.client.lavalink = lavalink.Client(client.user.id)
            self.client.lavalink.add_node(
                host="localhost",
                port=2333,
                password="lmP&jbL!3VzjG51",
                region="br",
                name="default-node"
            )
            self.lavalink = self.client.lavalink

    async def on_voice_server_update(self, data) -> None:
        lavalink_data = {
            "t": "VOICE_SERVER_UPDATE",
            "d": data
        }
        await self.lavalink.voice_update_handler(lavalink_data)

    async def on_voice_state_update(self, data) -> None:        
        lavalink_data = {
            "t": "VOICE_STATE_UPDATE",
            "d": data
        }
        await self.lavalink.voice_update_handler(lavalink_data)

    async def connect(self, *, reconnect: bool, timeout: float, self_deaf: bool = False, self_mute: bool = False) -> None:
        self.lavalink.player_manager.create(guild_id=self.channel.guild.id)
        await self.channel.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)

    async def disconnect(self, *, force: bool = False) -> None:
        player: lavalink.BasePlayer = self.lavalink.player_manager.get(self.channel.guild.id)

        if not force and not player.is_connected:
            return

        await self.channel.guild.change_voice_state(channel=None)

        player.channel_id = None
        self.cleanup()

class Bot(discord.Client):
    """Main Bot class"""
    def __init__(self, *, intents: discord.Intents, **kwargs) -> None:
        super().__init__(intents=intents, **kwargs)

        self.tree = app_commands.CommandTree(self)
        
        lavalink.add_event_hook(self.track_hook)

    async def setup_hook(self) -> None:
        self.tree.copy_global_to(guild=guild_id)
        await self.tree.sync(guild=guild_id)

    async def track_hook(self, event: lavalink.Event):
        """Hook for lavalink track events

        Notes
        -----
        Currently only checks for QueueEndEvent and disconnects from voice channel
        after `inactive_timeout`

        Parameters
        ----------
        event : lavalink.Event
        """
        if isinstance(event, lavalink.events.QueueEndEvent):
            player: lavalink.DefaultPlayer = event.player
            await player.stop()
            time = 0
            while time < inactive_timeout:
                await asyncio.sleep(1)
                time += 1
                if player.is_playing:
                    break
            else:
                vc = discord.utils.get(self.voice_clients, guild=discord.utils.get(self.guilds, id=player.guild_id))
                await vc.disconnect()

# Setup the default intents + message_contents
intents = discord.Intents.default()
intents.message_content = True
# Main bot instance
client = Bot(intents=intents)
# YoutubeDL instace for getting track data not given from Lavalink
# Currently only used to get thumbnail links
ydl = youtube_dl.YoutubeDL({"quiet": True})

@client.event
async def on_ready():
    """Event that runs right after bot initialization

    Used for Lavalink setup
    """
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")

    # Checks if client already has a Lavalink client and create ones if it doesn't
    if not hasattr(client, "lavalink"):
        client.lavalink = lavalink.Client(client.user.id)
        client.lavalink.add_node(
            host="localhost",
            port=2333,
            password="lmP&jbL!3VzjG51",
            region="br",
            name="default-node"
        )

def is_connected_to_voice_channel():
    """Decorator that checks if the user is currently connected to a voice channel"""
    def predicate(interaction: discord.Interaction) -> bool:
        return True if interaction.user.voice is not None else False

    return app_commands.check(predicate)

async def _join(interaction: discord.Interaction) -> None:
    """Inner function that handles connecting to a voice channel

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object

    Raises
    ------
    app_commands.errors.BotMissingPermissions
        Bot doesn't have the necessary permissions to join a/this channel
    """
    user_channel = interaction.user.voice.channel
    client = discord.utils.get(interaction.client.voice_clients, guild=interaction.guild)
    member = interaction.guild.get_member(interaction.client.user.id)
    
    # Check if the bot has the necessary permissions to enter a voice channel
    permissions = user_channel.permissions_for(member)
    if not permissions.connect:
        raise app_commands.errors.BotMissingPermissions(["See your voice channel"])
    if client is not None:
        await client.move_to(user_channel)
        return user_channel

    await user_channel.connect(cls=LavalinkVoiceClient)
    return user_channel

@client.tree.command()
@is_connected_to_voice_channel()
async def join(interaction: discord.Interaction):
    """Joins the user current voice channel

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object

    Raises
    ------
    app_commands.errors.BotMissingPermissions
        Bot doesn't have the necessary permissions to join a/this channel
    app_commands.errors.CheckFailure
        User not connected to any voice channel
    """
    user_channel = await _join(interaction)
    await interaction.response.send_message(f"Joining {user_channel}")

@join.error
async def join_error_handler(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Handler for errors triggered when using the join command

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    error : discord.app_commands.AppCommandError
        The error that occured
    """
    if isinstance(error, app_commands.errors.BotMissingPermissions):
        await interaction.response.send_message(f"I need the following permissions to run this command: {'&'.join(error.missing_permissions)}")
    elif isinstance(error, app_commands.errors.CheckFailure):
        await interaction.response.send_message("You need to be connected to a voice channel to run this command", ephemeral=True)

@client.tree.command()
@is_connected_to_voice_channel()
async def leave(interaction: discord.Interaction):
    """Leaves the current voice channel and stops the player

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object

    Raises
    ------
    NotInSameVoiceChannelError
        User who used the command is not on the same voice channel as the bot
    app_commands.errors.CheckFailure
        User not connected to any voice channel
    """
    player = get_player(interaction)
    user_channel = interaction.user.voice.channel

    # Check if bot and user channels are the same
    if user_channel != discord.utils.get(interaction.client.voice_clients, guild=interaction.guild).channel:
        raise NotInSameVoiceChannelError("We need to be in the same voice channel for this to work")

    client = discord.utils.get(interaction.client.voice_clients, guild=interaction.guild)

    await player.stop()
    await client.disconnect()

@leave.error
async def leave_error_handler(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Handler for errors triggered when using the leave command

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    error : discord.app_commands.AppCommandError
        The error that occured
    """
    if isinstance(error, NotInSameVoiceChannelError):
        await interaction.response.send_message("You need to be in the same voice channel as me to run this command", ephemeral=True)
    elif isinstance(error, app_commands.errors.CheckFailure):
        await interaction.response.send_message("You need to be connected to a voice channel to run this command", ephemeral=True)

@client.tree.command()
@is_connected_to_voice_channel()
@app_commands.rename(query="link-or-query")
@app_commands.describe(query="Link or query to search for")
async def play(interaction: discord.Interaction, query: str):
    """Plays a song for the given url or search query """
    user_channel = await _join(interaction)

    # Check if bot and user channel are the same
    if user_channel != discord.utils.get(interaction.client.voice_clients, guild=interaction.guild).channel:
        raise app_commands.errors.CommandInvokeError("We need to be in the same voice channel for this to work")

    player = get_player(interaction)

    player.store("channel", user_channel)

    if not url_rx.match(query):
        query = f"ytsearch:{query}"

    # Get the results for the given query
    results: lavalink.LoadResult = await player.node.get_tracks(query)

    if not results or not results.tracks:
        return await interaction.response.send_message("No tracks were found", ephemeral=True)

    embed = discord.Embed(color=embed_color)

    # Valid loadTypes are:
    #   TRACK_LOADED    - single video/direct URL)
    #   PLAYLIST_LOADED - direct URL to playlist)
    #   SEARCH_RESULT   - query prefixed with either ytsearch: or scsearch:.
    #   NO_MATCHES      - query yielded no results
    #   LOAD_FAILED     - most likely, the video encountered an exception during loading.

    match results.load_type:
        case "PLAYLIST_LOADED":
            tracks = results.tracks

            for track in tracks:
                player.add(requester=interaction.user.id, track=track)

            embed.title = "Playlist enqueued"
            embed.description = f"{len(tracks)} tracks from {results.playlist_info.name}"
            await interaction.response.send_message(embed=embed)
            if not player.is_playing:
                await player.play()

        case "SEARCH_RESULT":
            tracks = results.tracks[0:5]
            embed.title = "Choose a track from the buttons bellow"
            view = discord.ui.View()
            def create_callback(track: lavalink.AudioTrack | lavalink.DeferredAudioTrack):
                async def callback(interaction: discord.Interaction):
                    player.add(requester=interaction.user.id, track=track)
                    if not player.is_playing:
                        await player.play()

                    embed.title = "Track enqueued"
                    embed.description = f"[{track.title}]({track.uri})"

                    thumb_url = ydl.extract_info(track.uri, download=False)["thumbnails"][-1]["url"]
                    embed.set_image(url=thumb_url)
                    embed.clear_fields()
                    view.clear_items()
                    await interaction.response.edit_message(view=view, embed=embed)

                return callback
            for track in tracks:
                track_index = tracks.index(track)
                embed.add_field(name="\u200b", value=f"**{track_index + 1}:** [{track.title}]({track.uri})", inline=False)
                
                button = discord.ui.Button(style=discord.ButtonStyle.primary, label=track_index + 1)
                button.callback = create_callback(track)

                view.add_item(button)

            await interaction.response.send_message(embed=embed, view=view)
        case "TRACK_LOADED":
            track = results.tracks[0]
            embed.title = "Track enqueued"
            embed.description = f"[{track.title}]({track.uri})"

            player.add(requester=interaction.user.id, track=track)

            await interaction.response.send_message(embed=embed)
            if not player.is_playing:
                await player.play()
        case "NO_MATCHES":
            await interaction.response.send_message("No tracks where found")
        case "LOAD_FAILED":
            await interaction.response.send_message("Failed to load video")
        case _:
            await interaction.response.send_message("An unknown error ocurred while loading the video")

@play.error
async def play_error_handler(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Handler for errors triggered when using the leave command

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    error : discord.app_commands.AppCommandError
        The error that occured
    """
    if isinstance(error, app_commands.errors.BotMissingPermissions):
        error.missing_permissions.append("Speak in your voice channel")
        await interaction.response.send_message(f"I need the following permissions to run this command: {' & '.join(error.missing_permissions)}", ephemeral=True)
    elif isinstance(error, app_commands.errors.CommandInvokeError):
        await interaction.response.send_message(error, ephemeral=True)

@client.tree.command()
async def stop(interaction: discord.Interaction):
    """Stops the player and clears the queue

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    """
    player = get_player(interaction)
    
    await player.stop()
    await interaction.response.send_message("Stopped")

@client.tree.command()
async def pause(interaction: discord.Interaction):
    """Pauses the player
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    """
    player = get_player(interaction)

    if player.is_playing:
        await player.set_pause(True)
        return await interaction.response.send_message("Paused")
    await interaction.response.send_message("Not currently playing anything")

@client.tree.command()
async def resume(interaction: discord.Interaction):
    """Resume the player
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    """
    player = get_player(interaction)

    if player.paused:
        await player.set_pause(False)
        return await interaction.response.send_message("Resumed")
    await interaction.response.send_message("Not currently paused")

@client.tree.command()
@app_commands.describe(amount="Number of tracks to skip")
async def skip(interaction: discord.Interaction, amount: int = 1):
    """Skips the current or the given amount of tracks

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    amount : int, optional
        Number of tracks to skip, by default 1
    """
    player = get_player(interaction)

    if len(player.queue) <= 0:
        return await interaction.response.send_message("Unable to skip track, queue is currently empty")

    if amount <= 0:
        return await interaction.response.send_message("Please use a value bigger then or equal to 1")

    for _ in range(amount):
        await player.skip()
        
    await interaction.response.send_message("Skipped")

@client.tree.command()
async def nowplaying(interaction: discord.Interaction):
    """Shows the current playing track
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    """
    player = get_player(interaction)

    embed = discord.Embed(color=embed_color)
    embed.title = "Now playing"
    embed.description = f"[{player.current.title}]({player.current.uri}) Remaining: {get_duration(player.current.duration - player.position)}"
    thumb_url = ydl.extract_info(player.current.uri, download=False)["thumbnails"][-1]["url"]
    embed.set_image(url=thumb_url)

    await interaction.response.send_message(embed=embed)

@client.tree.command()
async def loop(interaction: discord.Interaction):
    """Shows if the player is currently looping
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    """
    player = get_player(interaction)

    msg = ""
    if player.loop == 0: msg = "off"
    elif player.loop == 1: msg = "track"
    elif player.loop == 2: msg = "queue"

    await interaction.response.send_message(f"Currently looping is set to {msg}")

@client.tree.command()
async def loopoff(interaction: discord.Interaction):
    """Turns looping off
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object"""
    player = get_player(interaction)

    player.set_loop(0)

    await interaction.response.send_message(f"Turned off looping")

@client.tree.command()
async def looptrack(interaction: discord.Interaction):
    """Loops the current track
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    """
    player = get_player(interaction)

    player.set_loop(1)

    await interaction.response.send_message(f"Now looping the current track")

@client.tree.command()
async def loopqueue(interaction: discord.Interaction):
    """Loops the queue, starting from the current track
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    """
    player = get_player(interaction)

    player.set_loop(2)

    await interaction.response.send_message(f"Now looping the queue")

@client.tree.command()
@app_commands.describe(strength="Strength of the filter. From 0 (off) to 100")
async def lowpass(interaction: discord.Interaction, strength: float):
    """Apply LowPass filter on current track
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    strength : float
        Strength of the filter. From 0 (off) to 100 (max)
    """
    player = get_player(interaction)

    strength = max(0.0, min(100, strength))

    if strength == 0.0:
        await player.remove_filter("lowpass")
        return await interaction.response.send_message("Removed **LowPass filter**")
    
    lp = lavalink.filters.LowPass()
    lp.update(smoothing=strength)

    await player.set_filter(lp)

    await interaction.response.send_message("Applied **LowPass filter**")

@client.tree.command()
@app_commands.describe(page="Page to look at")
async def queue(interaction: discord.Interaction, page: int = 1):
    """Shows the upcoming tracks
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    page : int, optional
        Page to retrieve the track from, deafault is 1
    """
    player = get_player(interaction)

    max_tracks_per_page = 10

    queue = player.queue

    pages = int(math.ceil(len(queue) / max_tracks_per_page))

    if len(queue) <= 0:
        return await interaction.response.send_message("Queue is currently empty")
    if page <= 0 or page > pages:
        return await interaction.response.send_message(f"Page out of bounds, please use a value between {1}-{pages}")

    embed = discord.Embed(color=embed_color)
    embed.title = "Upcoming tracks"

    if len(queue) > max_tracks_per_page:
        begin = (page - 1) * max_tracks_per_page
        end = begin + max_tracks_per_page
        tracks_to_show = queue[begin:end] if end < len(queue) else queue[begin:len(queue)]

        for track in tracks_to_show:
            duration = get_duration(track.duration)
            requester = interaction.guild.get_member(track.requester)
            embed.add_field(name="\u200b",
                            value=f"**{queue.index(track) + 1}: {track.title}** ({duration}) Requested by: {requester.display_name}",
                            inline=False)
    else:
        for track in queue:
            duration = get_duration(track.duration)
            requester = interaction.guild.get_member(track.requester)
            embed.add_field(name="\u200b",
                            value=f"**{queue.index(track) + 1}: {track.title}** ({duration}) Requested by: {requester.display_name}",
                            inline=False)

    
    embed.set_footer(text=f"Page {page} out of {pages}")
    await interaction.response.send_message(embed=embed)

@client.tree.command()
async def shuffle(interaction: discord.Interaction):
    """Shuffles the current queue
    
    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object
    """
    player = get_player(interaction)

    random.shuffle(player.queue)

    await interaction.response.send_message("Shuffled queue")

def run() -> None:
    """Starts the bot"""
    client.run(token)