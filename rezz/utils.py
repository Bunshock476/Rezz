"""Series of utility functions"""

from discord import Interaction
from lavalink import DefaultPlayer

def get_player(interaction: Interaction) -> DefaultPlayer:
    """ Gets the player from the guild the Interaction was called from

    Parameters
    ----------
    interaction : discord.Interaction
        Discord.py Interaction object

    Returns
    -------
    lavalink.DefaultPlayer
        Player for this interaction's guild
    """
    return interaction.client.lavalink.player_manager.get(interaction.guild.id)

def get_duration(ms: int) -> str:
    """ Converts a time in milliseconds to a string of minutes and seconds formatted as '%M:%S'

    Parameters
    ----------
    ms : int
        Amount of milliseconds

    Returns
    -------
    str
        String of minutes and seconds formatted as '%M:%S'
    """
    seconds=(ms/1000)%60
    seconds = str(int(seconds))
    minutes=(ms/(1000*60))%60
    minutes = int(minutes)
    return f"{minutes}:{seconds if int(seconds) >= 10 else '0'+seconds}"