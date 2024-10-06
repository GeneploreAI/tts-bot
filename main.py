import discord
import os
import calendar
from discord import app_commands
import asyncio
import base64
from discord.app_commands import Choice
import json
from discord import ui
from discord.ext import tasks
from dotenv import load_dotenv
import datetime
import aiofiles
import aiohttp
from concurrent.futures import ThreadPoolExecutor
import openai
import random
import io
import math
import moviepy
from moviepy.editor import AudioFileClip, ImageClip, VideoFileClip
from google.cloud import texttospeech

# ONE CREDIT IS ONE CHARACTER FOR A MODEL THAT COSTS $1 per MILLION CHARACTERS

load_dotenv()


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MONGODB_URL = os.getenv("MONGODB_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.server_api import ServerApi

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.reactions = True

client = discord.AutoShardedClient(intents=intents)

tree = discord.app_commands.CommandTree(client=client)
client.tree = tree


dbclient = AsyncIOMotorClient(MONGODB_URL, server_api=ServerApi('1'))
db = dbclient['tts-bot']

activated_channels = []

@client.event
async def on_connect():
    if client.user.id == 1289280100956635209:
        client.testing = False
    elif client.user.id == 1291807442942034093:
        client.testing = True

    global debug_channel_id
    
    if client.testing:
        debug_channel_id = 1257507203275952160
    else:
        debug_channel_id = 1100527117244051529

    global geneplore_server_id

    if client.testing:
        geneplore_server_id = 1116445293727203358
    else:
        geneplore_server_id = 1092173065967911002

    global loading_reaction
    if client.testing:
        loading_reaction = "🔄"
    else:
        loading_reaction = "<a:loading:1241186758838976654>"

    if activated_channels == []:
        async for i in db.guilds.find({"settings.activated_channels": {"$exists": True}}):
            for i in i["settings"]["activated_channels"]:
                activated_channels.append(i)

    if not DayCapReset.is_running():
        DayCapReset.start()

    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name="try me with /tts!"))

async def GetUser(id):
    if id == None:
        return None
    user = await db.users.find_one({"id": id})
    if user == None:
        await db.users.insert_one({"id": id, "subscription": None, "total_messages": 0, "total_activity": 0, "last_interaction": datetime.datetime.now()})
        user = await db.users.find_one({"id": id})
    return user

async def GetGuild(rawguild):
    if rawguild == None:
        return {}

    guild = await db.guilds.find_one({"id": rawguild.id})
    if guild == None:
        await db.guilds.insert_one({"id": rawguild.id, "settings": {}})
        guild = await db.guilds.find_one({"id": rawguild.id})
    return guild

async def PremiumCheck(rawuser: discord.User, rawguild: discord.Guild | None, addons: list = []) -> bool | discord.Embed:
    user = await GetUser(rawuser.id)
    if not user.get("subscription"):
        user["subscription"] = {}
    
    guild = await GetGuild(rawguild)
    if not guild:
        guild = {}
    if not guild.get("subscription"):
        guild["subscription"] = {}

    if isinstance(guild.get("subscription"), str):
        guild["subscription"] = {
            "tier": guild.get("subscription"),
            "sku_id": None,
            "starts_at": guild.get("datesubscribed"),
            "ends_at": None

        }
        await db.guilds.replace_one({"id": rawguild.id}, guild)
        guild = await GetGuild(rawguild)

    if isinstance(user.get("subscription"), str):
        user["subscription"] = {
            "tier": user.get("subscription"),
            "sku_id": None,
            "starts_at": user.get("datesubscribed"),
            "ends_at": None

        }
        await db.users.replace_one({"id": rawuser.id}, user)
        user = await GetUser(rawuser.id)

    if user.get("subscription", {}).get("ends_at"):
        print(datetime.datetime.now() - user.get("subscription", {}).get("ends_at"))
        print(user.get("subscription", {}).get("ends_at"))
        if user.get("subscription", {}).get("ends_at") < datetime.datetime.now():
            await db.users.update_one({"id": rawuser.id}, {"$set": {"subscription": None}})
            await db.users.update_one({"id": rawuser.id}, {"$set": {"daily_limit": 500}})
            user["subscription"] = None
    if not user.get("subscription") and not guild.get("subscription"):
        for i in addons:
            if i in user.get("addons", []):
                return False

        
        return GetPremiumEmbed()
    



    if guild.get("subscription", {}).get("ends_at"):
        print(datetime.datetime.now() - guild.get("subscription", {}).get("ends_at"))
        print(guild.get("subscription", {}).get("ends_at"))
        if guild.get("subscription", {}).get("ends_at") < datetime.datetime.now():
            await db.guilds.update_one({"id": rawguild.id}, {"$set": {"subscription": None}})
            await db.guilds.update_one({"id": rawguild.id}, {"$set": {"daily_limit": 5000}})
            guild["subscription"] = None

    return False

    

def isAddedToGuild(interaction):
    return interaction.is_guild_integration()

async def Analytics(raw: discord.Interaction | discord.Message, reason = None):
    try:

        if isinstance(raw, discord.Interaction):
            user = raw.user
            guild = raw.guild
            if not guild:
                guild = {"id": None}
        

        elif isinstance(raw, discord.Message):
            user = raw.author
            guild = raw.guild
            if not guild:
                guild = {"id": None}

        
        await GetUser(user.id)

        
        await db.users.update_one({"id": user.id}, {"$set": {"last_interaction": datetime.datetime.now()}})
        await db.users.update_one({"id": user.id}, {"$inc": {"total_activity": 1}})

        if guild:
            await GetGuild(guild)
            await db.guilds.update_one({"id": guild.id}, {"$set": {"last_interaction": datetime.datetime.now()}})
            await db.guilds.update_one({"id": guild.id}, {"$inc": {"total_activity": 1}})
    except:
        return

    await GetUser(user.id)
    await db.users.update_one({"id": user.id}, {"$set": {"last_interaction": datetime.datetime.now()}})
    await db.users.update_one({"id": user.id}, {"$inc": {"total_activity": 1}})

async def ErrorEmbed(error, message_id, user_id, command, title = "Unknown Error"):
    embed = discord.Embed(title=title, description=error + "\n\nNeed support? Join our support server at https://geneplore.com/discord", color=discord.Color.red())
    embed.set_footer(text="Error ID: " + str(message_id))
    await db.errors.insert_one({"id": message_id, "user_id": user_id, "error": error, command: command, "time": datetime.datetime.now()})
    return embed


class PremiumButton(ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.blurple, sku_id=1291473520139829381)
        #super().__init__(style=discord.ButtonStyle.blurple, label="Subscribe to TTS Pro", emoji="✨", url="https://discord.com/application-directory/1196486148046983168/store/1267577604114743357")

class ListentoPremiumTTSButton(ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.gray, label="Hear the difference", emoji="🔊")
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        session = aiohttp.ClientSession()
        req = await session.get("https://geneplo.re/static/hosted/bot-audio/TTS-PremiumB.mp3")
        audio = io.BytesIO(await req.read())
        req2 = await session.get("https://geneplo.re/static/hosted/bot-audio/TTS-Premium.mp3")
        audio2 = io.BytesIO(await req2.read())
        await session.close()

        view = SpeechView()
        await interaction.edit_original_response(attachments=[discord.File(fp=audio, filename="speech.mp3"), discord.File(fp=audio2, filename="speech2.mp3")], view=view, embed=None)

        botmessage = await interaction.original_response()
        view.message = botmessage

class PremiumView(ui.View):
    def __init__(self, ispremium = False):
        super().__init__(timeout=None)
        if not ispremium:
            self.add_item(PremiumButton())
            self.add_item(ListentoPremiumTTSButton())
        else:
            self.add_item(ui.Button(style=discord.ButtonStyle.gray, label="Sorry for the interruption!", disabled=True))
  
        
@tree.command(name="help", description="Get help with TTS.")
async def help(interaction: discord.Interaction):
    await Analytics(interaction)
    embed = discord.Embed(title="TTS Help", color=0x18def0, url="https://discord.gg/JCnxEaE3Mx", description="TTS is a Discord bot built on OpenAI's Text to Speech API. Run /tts or /join to try me!")

    count = await db.conversations.count_documents({})
    embed.set_footer(text=str(len(client.users)) + " users | " + str(len(client.guilds)) + " servers | " + str(count) + " conversations")
    embed.set_thumbnail(url="https://geneplo.re/static/hosted/bot-img/TTS.png")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    

@tree.command(name="premium", description="Subscribe for lower limits, more features and TTS voices.")
async def help(interaction: discord.Interaction):
    await Analytics(interaction)
    embed = GetPremiumEmbed()
    view = PremiumView()
    
    await interaction.response.send_message(view=view, embed=embed, ephemeral=True)

def NextMidnight() -> datetime.datetime:
    current = datetime.datetime.now()
    repl = current.replace(hour=0, minute=0, second=0, microsecond=0)
    while repl <= current:
        repl = repl + datetime.timedelta(days=1)
    return repl

"""
def RunPyTTS(prompt: str, r, speed: float = 1.0):
    engine = pytts.init()
    engine.setProperty("rate", speed * 200)
    engine.save_to_file(prompt, "files/" + str(r) + ".mp3")
    engine.runAndWait()
    return
    

async def PythonTTS(prompt: str, r: int, speed: float = 1.0):
    with ThreadPoolExecutor() as executor:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(executor, lambda: RunPyTTS(prompt, r, speed))
    return
"""

async def GetModelSelects() -> list:
    selects = []
    async for i in db.models.find({"published": True}).sort("sort", 1):
        if i.get("is_premium"):
            common = i.get("common_name") + " ⭐"
        else:
            common = i.get("common_name")
        selects.append(discord.SelectOption(label=common, value=i.get("name"), emoji=i.get("emoji"), description=i.get("description")))

    return selects

async def GetVoiceSelects(model) -> list:
    selects = []
    async for i in db.voices.find({"models": model}).sort("sort", 1):
        if i.get("is_premium"):
            common = i.get("common_name") + " ⭐"
        else:
            common = i.get("common_name")
        selects.append(discord.SelectOption(label=common, value=i.get("name")))

    return selects


def GetPremiumEmbed():
    embed = discord.Embed(title="Premium Only", description="This feature is only available to TTS Premium subscribers. Subscribe to TTS Premium for access to more voices and features.", color=discord.Color.blue())
    embed.set_thumbnail(url="https://geneplo.re/static/hosted/bot-img/TTS.png")
    return embed

def GetDailyLimitEmbed(delta, ispremium = False):
    if ispremium:
        embed = discord.Embed(title="Daily limit reached.", description=f"You have reached your daily limit. Wait {delta} for your limit to reset.", color=discord.Color.red())
    else:
        embed = discord.Embed(title="Daily limit reached.", description=f"You have reached your daily limit. Subscribe to TTS Premium for higher limits or wait {delta} for a refill.", color=discord.Color.red())
    embed.set_thumbnail(url="https://geneplo.re/static/hosted/bot-img/TTS.png")
    return embed


async def RunTTS(prompt: str, interaction: discord.Interaction | discord.Message = None, islive = False, model: str = None, voice: str = None, session: aiohttp.ClientSession = None) -> discord.Embed | io.BytesIO:



    if isinstance(interaction, discord.Interaction):
        rawuser = interaction.user
        rawguild = interaction.guild
        user = await GetUser(interaction.user.id)
        ulocale = interaction.locale
        if user.get("settings", {}).get("locale") != ulocale:
            await db.users.update_one({"id": user.get("id")}, {"$set": {"settings.locale": ulocale.value}})
        if interaction.guild != None:
            guild = await GetGuild(interaction.guild)
            glocale = interaction.guild.preferred_locale
            if guild.get("settings", {}).get("locale") != glocale:
                await db.guilds.update_one({"id": guild.get("id")}, {"$set": {"settings.locale": glocale.value}})

        else:
            guild = {}
    elif isinstance(interaction, discord.Message):
        rawuser = interaction.author
        rawguild = interaction.guild
        user = await GetUser(interaction.author.id)
        if interaction.guild != None:
            guild = await GetGuild(interaction.guild)
        else:
            guild = {}

    elif interaction == None:
        user = {}
        guild = {}

    #find likely locale
    if user.get("settings", {}).get("locale"):
        locale = user.get("settings", {}).get("locale")
    elif guild.get("settings", {}).get("locale"):
        locale = guild.get("settings", {}).get("locale")
    else:
        locale = "en-US"

    if not model:
        if guild:
            model = guild.get("settings", {}).get("model", "google-standard")
        else:
            model = user.get("settings", {}).get("model", "google-standard")

    if not voice:
        if guild:
            voice = guild.get("settings", {}).get("tts_voice", "alloy")
        else:
            voice = user.get("settings", {}).get("tts_voice", "alloy")


    
    if islive:
        refilltime = datetime.datetime.timestamp((NextMidnight()))
        delta = NextMidnight() - datetime.datetime.now()
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        refilltime = str(hours) + " hours and " + str(minutes) + " minutes"
    else:
        refilltime = "<t:" + str(math.ceil(datetime.datetime.timestamp(NextMidnight()))) + ":R>"
    

    premium = await PremiumCheck(rawuser, rawguild)
    if premium:
        ispremium = False
    else:
        ispremium = True
        
    dbmodel = await db.models.find_one({"name": model})
    if dbmodel["is_premium"]:
        if not ispremium:
            return premium

    if not guild:
        if user.get("daily_usage", 0) > user.get("daily_limit", 500):
            return GetDailyLimitEmbed(refilltime, ispremium=ispremium), PremiumView(ispremium=ispremium)
    else:
        if guild.get("daily_usage", 0) > guild.get("daily_limit", 2500):
            return GetDailyLimitEmbed(refilltime, ispremium=ispremium), PremiumView(ispremium=ispremium)

    if not isinstance(session, aiohttp.ClientSession):
        session = aiohttp.ClientSession()



    if model in ["tts-1", "tts-1-hd"]:

        data = {
            "model": model,
            "input": prompt,
            "voice": voice

        }
        if guild:
            data["speed"] = guild.get("settings", {}).get("speed", 1.0)
        if islive:
            data["response_format"] = "opus"
        headers = {"Authorization": "Bearer " + openai.api_key, "Content-Type": "application/json"}

        req = await session.post(url="https://api.openai.com/v1/audio/speech", data=json.dumps(data), headers=headers)
        audio = await req.read()
        audio = io.BytesIO(audio)

        if model == "tts-1":
            cost = len(prompt) * 15
        elif model == "tts-1-hd":
            cost = len(prompt) * 30

    #if model == "pytts":
    #    r = random.randint(1, 99999999999)
    #    await PythonTTS(prompt, r=r, speed=guild.get("settings", {}).get("speed", 1.0))
    #    f = await aiofiles.open("files/" + str(r) + ".mp3", "rb")
    #    audio = io.BytesIO(await f.read())
    #    cost = len(prompt)
    print(model)
    if "google" in model:
        synthesis_input = texttospeech.SynthesisInput(text=prompt)
        if voice == "MASCULINE":
            gender = texttospeech.SsmlVoiceGender.MALE
        elif voice == "FEMININE":
            gender = texttospeech.SsmlVoiceGender.FEMALE
        else:
            gender = texttospeech.SsmlVoiceGender.MALE

        if model == "google-standard":
            gmodel = "Standard"
        elif model == "google-journey":
            gmodel = "Journey"
        elif model == "google-wavenet":
            gmodel = "Wavenet"
        elif model == "google-neural2":
            gmodel = "Neural2"
        else:
            gmodel = "Standard"

        print(gmodel)

        googletts = texttospeech.TextToSpeechAsyncClient()

        voices = await googletts.list_voices(language_code=locale)
        modelvoices = []
        for v in voices.voices:
            if gmodel in v.name:
                modelvoices.append(v)
        
        if not modelvoices:
            return await ErrorEmbed("No voices available for this model in your language. Please change your language in your Discord settings.", interaction.id, rawuser.id, "RunTTS", title="No voices available")
            
        for i in modelvoices:
            if i.ssml_gender == gender:
                voice = i
                break

        if not voice:
            voice = modelvoices[0]



        voice = texttospeech.VoiceSelectionParams(
            language_code=locale, name=voice.name
        )


        print(voice)

        if islive:
            encoding = texttospeech.AudioEncoding.OGG_OPUS
        else:
            encoding = texttospeech.AudioEncoding.MP3
        audio_config = texttospeech.AudioConfig(
            audio_encoding=encoding,
            speaking_rate=guild.get("settings", {}).get("speed", 1.0),
        )

        

        resp = await googletts.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        audio = io.BytesIO(resp.audio_content)
        costm = dbmodel.get("pricing", {}).get("costpermillion", 1)
        if model in ["google-standard", "google-wavenet"]:
            cost = len(prompt) * costm
        elif model in ["google-journey", "google-neural2"]:
            cost = len(bytes(prompt, "utf-8")) * costm


    if guild:
        await db.guilds.update_one({"id": guild.get("id")}, {"$inc": {"daily_usage": cost}})
    else:
        await db.users.update_one({"id": user.get("id")}, {"$inc": {"daily_usage": cost}})

    if session:
        await session.close()
    return audio

"""
class HigherQualityTTSButton(ui.Button):
    def __init__(self, voice, prompt):
        super().__init__(style=discord.ButtonStyle.gray, label="Regenerate in HD", emoji="🔊")
        self.voice = voice
        self.prompt = prompt
    async def callback(self, interaction: discord.Interaction):
        user = await GetUser(interaction.user.id)

        if interaction.guild != None:
            guild = await GetGuild(interaction.guild)
        else:
            guild = {}

        prompt = self.prompt
        voice = self.voice




        await interaction.response.defer(thinking=True)
        audio = await RunTTS(prompt, interaction, model="tts-1-hd", voice=voice)

        if type(audio) == discord.Embed:
            await interaction.edit_original_response(embed=audio)
            return

        view = SpeechView()
        await interaction.edit_original_response(attachments=[discord.File(fp=audio, filename="speech.mp3")], view=view, embed=None)

        botmessage = await interaction.original_response()
        view.message = botmessage

class OtherVoiceButton(ui.Button):
    def __init__(self, voice, prompt, emoji):
        super().__init__(style=discord.ButtonStyle.gray, label='Generate with "' + voice + '"', emoji=emoji)
        self.voice = voice
        self.prompt = prompt
    async def callback(self, interaction: discord.Interaction):
        user = await GetUser(interaction.user.id)

        if interaction.guild != None:
            guild = await GetGuild(interaction.guild)
        else:
            guild = {}

        prompt = self.prompt
        voice = self.voice


        premium = await PremiumCheck(interaction.user, interaction.guild)
        if premium:
            await interaction.response.send_message(embed=premium, ephemeral=True)
            return
        
        
                

        await interaction.response.defer(thinking=True)

        audio = await RunTTS(prompt, interaction, model="tts-1", voice=voice)


        if type(audio) == discord.Embed:
            await interaction.edit_original_response(embed=audio)
            return


        view = SpeechView()
        await interaction.edit_original_response(attachments=[discord.File(fp=audio, filename="speech.mp3")], view=view, embed=None)

        botmessage = await interaction.original_response()
        view.message = botmessage
        messageurl = botmessage.jump_url
 

class ChangeVoiceButton(ui.Button):
    def __init__(self, voice, prompt):
        super().__init__(style=discord.ButtonStyle.gray, label='Change Voice', emoji="🔊")
        self.voice = voice
        self.prompt = prompt
    async def callback(self, interaction: discord.Interaction):
        voice = self.voice
        prompt = self.prompt
        self.view.clear_items()
        for i in TTSvoices.keys():
            if i != voice:
                self.view.add_item(OtherVoiceButton(i, prompt, TTSvoices[i]))


        await interaction.response.edit_message(view=self.view)

"""
class SpeechView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        #if model == "tts-1":
        #    self.add_item(HigherQualityTTSButton(voice, prompt))
        self.add_item(AudiotoVideoButton())

        #self.add_item(ChangeVoiceButton(voice, prompt))


    async def on_timeout(self) -> None:
        # Step 2
        for item in self.children:
            item.disabled = True

        await self.message.edit(view=self)


@tree.context_menu(name="Text to Speech")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.guild_install()
@app_commands.user_install()
async def respond(interaction: discord.Interaction, message: discord.Message):
    await Analytics(interaction)

    async def TTSMain(message):
        if interaction.guild != None:
            guild = await GetGuild(interaction.guild)
        else:
            guild = {}
        user = await GetUser(interaction.user.id)
        message.content = message.clean_content

        
                

        await interaction.response.defer(thinking=True)
        
        audio = await RunTTS(message.content, interaction)

        if type(audio) == tuple:
            await interaction.edit_original_response(embed=audio[0], view=audio[1])
            return

        if type(audio) == discord.Embed:
            await interaction.edit_original_response(embed=audio)
            return
        
        view = SpeechView()
        await interaction.edit_original_response(attachments=[discord.File(fp=audio, filename="speech.mp3")], view=view, embed=None)

        botmessage = await interaction.original_response()
        view.message = botmessage

        

    if isAddedToGuild(interaction):
        async with interaction.channel.typing():
            await TTSMain(message=message)
    else: 
        await TTSMain(message=message)


@tree.command(name="tts", description="Converts text to speech.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.guild_install()
@app_commands.user_install()
async def tts(interaction: discord.Interaction, prompt: str):
    await Analytics(interaction)

    async def TTSCommandMain(prompt):
        if interaction.guild != None:
            guild = await GetGuild(interaction.guild)
        else:
            guild = {}
        user = await GetUser(interaction.user.id)

                

        
        await interaction.response.defer(thinking=True)
        
        audio = await RunTTS(prompt, interaction)
        if type(audio) == tuple:
            await interaction.edit_original_response(embed=audio[0], view=audio[1])
            return


        if type(audio) == discord.Embed:
            await interaction.edit_original_response(embed=audio)
            return
        
        view = SpeechView()
        await interaction.edit_original_response(attachments=[discord.File(fp=audio, filename="speech.mp3")], view=view, embed=None)

        botmessage = await interaction.original_response()
        view.message = botmessage

        

    if isAddedToGuild(interaction):
        async with interaction.channel.typing():
            await TTSCommandMain(prompt=prompt)
    else: 
        await TTSCommandMain(prompt=prompt)


async def write_file(video_clip, output_path):

    with ThreadPoolExecutor() as executor:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(executor, lambda: video_clip.write_videofile(output_path))

    video_clip.close()

class AudiotoVideoButton(ui.Button):
    def __init__(self):
        super().__init__(label='Convert to Video', style=discord.ButtonStyle.primary, emoji="🎵")

    async def callback(self, interaction):
        #await interaction.response.send_message("Converting your music into a video...", ephemeral=True)
        await interaction.response.defer(thinking=True)
        file = await interaction.message.attachments[0].read()
        async with aiofiles.open("files/" + interaction.message.attachments[0].filename, "wb") as mp3_file:
            await mp3_file.write(file)

        audio_clip = AudioFileClip("files/" + interaction.message.attachments[0].filename)
        image_clip = ImageClip("gp_music.png")
        video_clip = image_clip.set_audio(audio_clip)
        video_clip.duration = audio_clip.duration
        video_clip.fps = 30
        file_path = "files/" + str(interaction.message.id) + "-" + str(random.randint(1, 99999999999)) + ".mp4"
        await write_file(video_clip, file_path)
        await interaction.edit_original_response(content="Here is your video:", attachments=[discord.File(file_path)])
        os.remove("files/" + interaction.message.attachments[0].filename)

class SettingsVoiceSelect(ui.Select):
    def __init__(self, voices, isuser=False):
        if not voices:
            super().__init__(placeholder="This model does not support voices.", options=[discord.SelectOption(label="No voices available", value="alloy")], disabled=True)
            return
        super().__init__(placeholder="Select a voice:", options=voices)
        self.isuser = isuser
    async def callback(self, interaction: discord.Interaction):
        voice = await db.voices.find_one({"name": self.values[0]})
        premium = await PremiumCheck(interaction.user, interaction.guild)
        if premium and voice.get("is_premium"):
            await interaction.response.send_message(embed=premium, ephemeral=True)
            return
        
        if self.isuser:
            await db.users.update_one({"id": interaction.user.id}, {"$set": {"settings.tts_voice": self.values[0]}})
            await interaction.response.send_message("Voice changed to " + voice["common_name"], ephemeral=True)
            return
        
        await db.guilds.update_one({"id": interaction.guild.id}, {"$set": {"settings.tts_voice": self.values[0]}})
        await interaction.response.send_message("Voice changed to " + voice["common_name"], ephemeral=True)

class SettingBoolButton(ui.Button):
    def __init__(self, guild, setting, user_facing_name, emoji, default):
        if guild.get("settings", {}).get(setting, default):
            color = discord.ButtonStyle.green
            onoff = " ON"
        else:
            color = discord.ButtonStyle.red
            onoff = " OFF"
        super().__init__(style=color, label=user_facing_name + onoff, emoji=emoji)
        self.setting = setting
        self.default = default
        self.user_facing_name = user_facing_name
    async def callback(self, interaction: discord.Interaction):
        guild = await GetGuild(interaction.guild)
        if guild.get("settings", {}).get(self.setting, self.default):
            await db.guilds.update_one({"id": interaction.guild.id}, {"$set": {"settings." + self.setting: False}})
            self.style = discord.ButtonStyle.red
            self.label = self.user_facing_name + " OFF"
            await interaction.response.edit_message(view=self.view)
        else:
            await db.guilds.update_one({"id": interaction.guild.id}, {"$set": {"settings." + self.setting: True}})
            self.style = discord.ButtonStyle.green
            self.label = self.user_facing_name + " ON"
            await interaction.response.edit_message(view=self.view)

class SettingsChannelSelect(ui.ChannelSelect):
    def __init__(self, guild):
        super().__init__(placeholder="Select channels to activate:", min_values=0, max_values=20)
    async def callback(self, interaction: discord.Interaction):
        activated_channels = []
        activated_pretty = ""
        for i in self.values:
            activated_channels.append(i.id)
            activated_pretty += "<#" + str(i.id) + ">, "
        await db.guilds.update_one({"id": interaction.guild.id}, {"$set": {"settings.activated_channels": activated_channels}})
        if self.values == []:
            await interaction.response.send_message("All channels have been activated.", ephemeral=True)
            return
        await interaction.response.send_message("Channels " + activated_pretty + " have been activated.", ephemeral=True)

class SettingsSpeedModal(ui.Modal):
    speed = ui.TextInput(label='Speed', required=True, placeholder="1.0")

    def __init__(self):
        super().__init__(title="Set the bot's speed")

    async def on_submit(self, interaction: discord.Interaction):
        speed = self.speed.value
        try:
            speed = float(speed)
        except:
            await interaction.response.send_message("Please enter a valid number.", ephemeral=True)
            return
        if speed < 0.25 or speed > 4.0:
            await interaction.response.send_message("Please enter a number between 0.25 and 4.0.", ephemeral=True)
            return
        await db.guilds.update_one({"id": interaction.guild.id}, {"$set": {"settings.speed": speed}})
        await interaction.response.send_message("Speed set to " + str(speed), ephemeral=True)

class SettingsSpeedButton(ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.gray, label="Change Speed", emoji="⏩")
    async def callback(self, interaction: discord.Interaction):
        modal = SettingsSpeedModal()
        await interaction.response.send_modal(modal)

class AdminRoleSelect(ui.RoleSelect):
    def __init__(self, guild):
        super().__init__(placeholder="Select roles to make settings available to:", min_values=0, max_values=20)
    async def callback(self, interaction: discord.Interaction):
        roles = []
        clean = ""
        for i in self.values:
            roles.append(i.id)
            clean += i.name + ", "
        await db.guilds.update_one({"id": interaction.guild.id}, {"$set": {"settings.admin_roles": roles}})

        await interaction.response.send_message("Roles `" + clean + "` can now access settings.", ephemeral=True)


class SettingsModelSelect(ui.Select):
    def __init__(self, models, isuser=False):
        super().__init__(placeholder="Select a model:", options=models)
        self.isuser = isuser
    async def callback(self, interaction: discord.Interaction):
        if self.isuser:
            await db.users.update_one({"id": interaction.user.id}, {"$set": {"settings.model": self.values[0]}})
            voice = await db.voices.find_one({"models": self.values[0]})
            if voice:
                await db.users.update_one({"id": interaction.user.id}, {"$set": {"settings.tts_voice": voice.get("name")}})
            view = SettingsView(user=await GetUser(interaction.user.id), rawuser=interaction.user, guild=await GetGuild(interaction.guild), rawguild=interaction.guild, models=await GetModelSelects(), uservoices=await GetVoiceSelects(model=self.values[0]), guildvoices=await GetVoiceSelects(model=self.values[0]), pagename="User")
            await interaction.response.edit_message(view=view)
            view.message = await interaction.original_response()
            return
        await db.guilds.update_one({"id": interaction.guild.id}, {"$set": {"settings.model": self.values[0]}})
        voice = await db.voices.find_one({"models": self.values[0]})
        if voice:
            await db.guilds.update_one({"id": interaction.guild.id}, {"$set": {"settings.tts_voice": voice.get("name")}})
        
        view = SettingsView(user=await GetUser(interaction.user.id), rawuser=interaction.user, guild=await GetGuild(interaction.guild), rawguild=interaction.guild, models=await GetModelSelects(), uservoices=await GetVoiceSelects(model=self.values[0]), guildvoices=await GetVoiceSelects(model=self.values[0]))
        await interaction.response.edit_message(view=view)
        view.message = await interaction.original_response()


def GetPage(page, guild, user, models, uservoices, guildvoices, rawuser, rawguild):  
    
    if page == "Server":
        for i in models:
            if i.value == guild.get("settings", {}).get("model", "google-standard"):
                i.default = True
            else:
                i.default = False
        for i in guildvoices:
            if i.value == guild.get("settings", {}).get("tts_voice", None):
                i.default = True
            else:
                i.default = False
    if page == "User":
        for i in models:
            if i.value == user.get("settings", {}).get("model", "google-standard"):
                i.default = True
            else:
                i.default = False
        for i in uservoices:
            if i.value == user.get("settings", {}).get("tts_voice", None):
                i.default = True
            else:
                i.default = False
        
    print(models)

    pages = {
        "Server": [
            SettingsChannelSelect(guild=guild),
            SettingsModelSelect(models),
            SettingsVoiceSelect(guildvoices),

            #buttons
            SettingsSpeedButton(),


            SettingBoolButton(guild=guild, setting="ignore_bots", user_facing_name="Ignore Bots", emoji="🤖", default=True),
            SettingBoolButton(guild=guild, setting="name_user", user_facing_name="Name User", emoji="👤", default=True),
            SettingBoolButton(guild=guild, setting="say_on_join", user_facing_name="Say on Join", emoji="👋", default=True),
            SettingBoolButton(guild=guild, setting="say_on_leave", user_facing_name="Say on Leave", emoji="👋", default=False),

        ],
        "Server (cont.)": [
            SettingBoolButton(guild=guild, setting="say_on_message", user_facing_name="Say on Message", emoji="📝", default=True),
            SettingBoolButton(guild=guild, setting="say_on_edit", user_facing_name="Say on Edit", emoji="📝", default=False),
            SettingBoolButton(guild=guild, setting="say_on_delete", user_facing_name="Say on Delete", emoji="🗑️", default=False),
            SettingBoolButton(guild=guild, setting="say_on_message", user_facing_name="Say on Message", emoji="📝", default=True),
            SettingBoolButton(guild=guild, setting="say_on_edit", user_facing_name="Say on Edit", emoji="📝", default=False),
            SettingBoolButton(guild=guild, setting="say_on_delete", user_facing_name="Say on Delete", emoji="🗑️", default=False)
        ],
        "Admin": [
            AdminRoleSelect(guild=guild)
        ],
        "User": [
            SettingsModelSelect(models, isuser=True),
            SettingsVoiceSelect(uservoices, isuser=True),
        ]

    }
    admin = False

    if not rawguild:
        pages.pop("Server")
        pages.pop("Server (cont.)")
        pages.pop("Admin")

    elif rawguild and guild.get("settings", {}).get("admin_roles", []) and not rawuser.guild_permissions.manage_guild:
        for i in guild.get("settings", {}).get("admin_roles", []):
            if i not in [i.id for i in rawuser.roles]:
                admin = True
                break
        if not admin:
            pages.pop("Server")
            pages.pop("Server (cont.)")

    if guild:
        if not rawuser.guild_permissions.manage_guild:
            pages.pop("Admin")

    return pages[page]






class LeftButton(ui.Button):
    def __init__(self, page, pagelist):
        if pagelist.index(page) == 0:
            isdisabled = True
        else:
            isdisabled = False
    
        if len(pagelist) == 1:
            isdisabled = True

        print(pagelist)
            
        super().__init__(emoji="◀", style=discord.ButtonStyle.secondary, disabled=isdisabled, row=4)
        self.pagelist = pagelist
    async def callback(self, interaction):
        pagelist = self.pagelist
        current = self.view.children[-2].label
        goto = pagelist[pagelist.index(current) - 1]
        guild = await GetGuild(interaction.guild)

        uservoices = await GetVoiceSelects(model=guild.get("settings", {}).get("model", "google-standard"))
        guildvoices = await GetVoiceSelects(model=guild.get("settings", {}).get("model", "google-standard"))
        page = GetPage(goto, guild=guild, user=await GetUser(interaction.user.id), models=await GetModelSelects(), uservoices=uservoices, guildvoices=guildvoices, rawuser=interaction.user, rawguild=interaction.guild)
        self.view.clear_items()
        for i in page:
            self.view.add_item(i)

        self.view.add_item(LeftButton(page=goto, pagelist=pagelist))
        self.view.add_item(ui.Button(label=goto, style=discord.ButtonStyle.secondary, emoji="📄", disabled=True, row=4))
        self.view.add_item(RightButton( page=goto, pagelist=pagelist))

        self.view.children[-2].disabled = True
        content = None
        await interaction.response.edit_message(content=content, view=self.view)

class RightButton(ui.Button):
    def __init__(self, page, pagelist):
        if pagelist.index(page) == len(pagelist)-1:
            isdisabled = True
        else:
            isdisabled = False

        if len(pagelist) == 1:
            isdisabled = True
            
        super().__init__(emoji="▶", style=discord.ButtonStyle.secondary, disabled=isdisabled, row=4)
        self.pagelist = pagelist
    async def callback(self, interaction):
        pagelist = self.pagelist
        current = self.view.children[-2].label
        goto = pagelist[pagelist.index(current) + 1]
        guild = await GetGuild(interaction.guild)
        user = await GetUser(interaction.user.id)

        uservoices = await GetVoiceSelects(model=user.get("settings", {}).get("model", "google-standard"))
        guildvoices = await GetVoiceSelects(model=guild.get("settings", {}).get("model", "google-standard"))
        page = GetPage(goto, guild=guild, user=await GetUser(interaction.user.id), models=await GetModelSelects(), uservoices=uservoices, guildvoices=guildvoices, rawuser=interaction.user, rawguild=interaction.guild)
        self.view.clear_items()
        for i in page:
            self.view.add_item(i)

        self.view.add_item(LeftButton(page=goto, pagelist=pagelist))
        self.view.add_item(ui.Button(label=goto, style=discord.ButtonStyle.secondary, emoji="📄", disabled=True, row=4))
        self.view.add_item(RightButton(page=goto, pagelist=pagelist))
        self.view.children[-2].disabled = True
        content = None

        await interaction.response.edit_message(content=content, view=self.view)




class SettingsView(ui.View):
    def __init__(self, user, rawuser, guild, rawguild, models, uservoices, guildvoices, pagename="Server"):
        super().__init__(timeout=600)
        #selects
        pagelist = ["Server", "Server (cont.)", "Admin", "User"]

        admin = False

        if not rawguild:
            pagename = "User"
            del pagelist[0]
            del pagelist[0]
            del pagelist[0]



        elif guild.get("settings", {}).get("admin_roles", []) and not rawuser.guild_permissions.manage_guild:
            for i in guild.get("settings", {}).get("admin_roles", []):
                if i in [i.id for i in rawuser.roles]:
                    admin = True
                    break
            if not admin:
                pagename = "User"
                del pagelist[0]
                del pagelist[0]
                del pagelist[0]

        elif not rawuser.guild_permissions.manage_guild:
            del pagelist[2]

        page = GetPage(pagename, guild=guild, user=user, models=models, uservoices=uservoices, guildvoices=guildvoices, rawuser=rawuser, rawguild=rawguild)
        for i in page:
            self.add_item(i)
        
        self.add_item(LeftButton(page=pagename, pagelist=pagelist))
        self.add_item(ui.Button(label=pagename, style=discord.ButtonStyle.secondary, emoji="📄", disabled=True, row=4))
        self.add_item(RightButton(page=pagename, pagelist=pagelist))





    
    async def on_timeout(self) -> None:
        # Step 2
        for item in self.children:
            item.disabled = True

        await self.message.edit(view=self)

@tree.command(name="settings", description="Change your settings.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.guild_install()
@app_commands.user_install()
async def settings(interaction: discord.Interaction):
    await Analytics(interaction)
    user = await GetUser(interaction.user.id)
    guild = await GetGuild(interaction.guild)
    view = SettingsView(user=user, rawuser=interaction.user, guild=guild, rawguild=interaction.guild, models=await GetModelSelects(), uservoices=await GetVoiceSelects(model=user.get("settings", {}).get("model", "google-standard")), guildvoices=await GetVoiceSelects(model=guild.get("settings", {}).get("model", "google-standard")))
    await interaction.response.send_message(view=view, ephemeral=True)
    view.message = await interaction.original_response()


connected_vcs = {}

vc_queue = {}

@tree.command(name="join", description="Join your voice channel.")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@app_commands.guild_install()
async def join(interaction: discord.Interaction):
    await Analytics(interaction)
    if interaction.guild:
        if interaction.guild.id in connected_vcs:
            await interaction.response.send_message("Already in a voice channel!", ephemeral=True)
            return
    else:
        await interaction.response.send_message("Stop your wizardry...", ephemeral=True)
        return
    voice_channel = interaction.user.voice.channel
    vc = await voice_channel.connect()
    connected_vcs[interaction.guild.id] = vc

@tree.command(name="leave", description="Leave your voice channel.")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@app_commands.guild_install()
async def leave(interaction: discord.Interaction):
    await Analytics(interaction)
    if interaction.guild.id not in connected_vcs:
        await interaction.response.send_message("Not in a voice channel!", ephemeral=True)
        return
    await interaction.response.send_message("Leaving your voice channel...", ephemeral=True)
    vc = connected_vcs[interaction.guild.id]
    await vc.disconnect()
    del connected_vcs[interaction.guild.id]

@tree.command(name="clear", description="Clears the TTS queue.")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
@app_commands.guild_install()
async def clear(interaction: discord.Interaction):
    await Analytics(interaction)
    if interaction.guild.id not in connected_vcs:
        await interaction.response.send_message("Not in a voice channel!", ephemeral=True)
        return
    if vc_queue.get(interaction.guild.id):
        vc_queue[interaction.guild.id] = []
    await interaction.response.send_message("Queue cleared!", ephemeral=True)


async def Speak(vc, audio):
    if vc.is_playing():
        if vc_queue.get(vc.channel.id):
            vc_queue[vc.channel.id] = vc_queue[vc.channel.id].append(audio)
        else:
            vc_queue[vc.channel.id] = [audio]
    else:
        vc_queue[vc.channel.id] = [audio]
        
    while audio in vc_queue.get(vc.channel.id, []):
        await asyncio.sleep(1)
        if not vc.is_playing():
            if vc_queue[vc.channel.id][0] == audio:
                vc.play(discord.FFmpegPCMAudio(audio, pipe=True))
                vc_queue[vc.channel.id].pop(0)
    
async def AnnounceError(vc, embed: discord.Embed = discord.Embed(title="An error occurred.", description="An error occurred while trying to speak.", color=discord.Color.red())):
    audio = await RunTTS(embed.description, None, islive=True, model="google-standard")
    await Speak(vc, audio)




@client.event
async def on_message_edit(before, after):
    if after.guild:
        if after.guild.id in connected_vcs:
            guild = await GetGuild(after.guild)
            if before.channel.id not in guild.get("settings", {}).get("activated_channels", []) and guild.get("settings", {}).get("activated_channels", []) != []:
                return
            if not guild.get("settings", {}).get("say_on_edit", False):
                return
            if before.author.bot and guild.get("settings", {}).get("ignore_bots", True):
                return
            vc = connected_vcs[after.guild.id]
            if guild.get("settings", {}).get("name_user", True):
                content = after.author.display_name + " edited a message to " + after.clean_content
            else:   
                content = "Someone edited a message."

                    
            
            audio = await RunTTS(content, before, islive=True)

            if type(audio) == discord.Embed:
                await AnnounceError(vc, audio)
                return

            
            await Speak(vc, audio)

@client.event
async def on_message_delete(before):
    print(before.guild)
    if before.guild:
        if before.guild.id in connected_vcs:
            guild = await GetGuild(before.guild)
            if before.channel.id not in guild.get("settings", {}).get("activated_channels", []) and guild.get("settings", {}).get("activated_channels", []) != []:
                return
            if not guild.get("settings", {}).get("say_on_delete", False):
                return
            if before.author.bot and guild.get("settings", {}).get("ignore_bots", True):
                return
            vc = connected_vcs[before.guild.id]
            if guild.get("settings", {}).get("name_user", True):
                content = before.author.display_name + " deleted a message."
            else:   
                content = "Someone deleted a message."

                    

            audio = await RunTTS(content, before, islive=True)

            if type(audio) == discord.Embed:
                await AnnounceError(vc, audio)
                return

            await Speak(vc, audio)

@client.event
async def on_message(message):
    if message.content == "!sync" and message.author.id == 766750708761493505:
        print("Syncing...")
        sync = await client.tree.sync()
        print(sync)
        await message.channel.send("Synced!")
        return
    if message.guild:
        if message.guild.id in connected_vcs:
            guild = await GetGuild(message.guild)
            if message.channel.id not in guild.get("settings", {}).get("activated_channels", []) and guild.get("settings", {}).get("activated_channels", []) != []:
                return
            if not guild.get("settings", {}).get("say_on_message", True):
                return
            if message.author.bot and guild.get("settings", {}).get("ignore_bots", True):
                return
            vc = connected_vcs[message.guild.id]
            if guild.get("settings", {}).get("name_user", True):
                content = message.author.display_name + " said " + message.clean_content
            else:   
                content = message.clean_content
                    

            
            audio = await RunTTS(content, message, islive=True)

            if type(audio) == discord.Embed:
                await AnnounceError(vc, audio)
                return

            await Speak(vc, audio)

@client.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    if member.guild.id in connected_vcs:
        guild = await GetGuild(member.guild)
        if not guild:
            guild = {}

        vc = connected_vcs[member.guild.id]

        if len(vc.channel.members) == 1:
            await vc.disconnect()
            del connected_vcs[member.guild.id]
    
        if before.channel == None and after.channel != None:
            if guild.get("settings", {}).get("say_on_join", False):
                content = member.display_name + " joined the voice channel."

                

        
                audio = await RunTTS(content, before)

                if type(audio) == discord.Embed:
                    await AnnounceError(vc, audio)
                    return

        
                await Speak(vc, audio)
        if before.channel != None and after.channel == None:
            if guild.get("settings", {}).get("say_on_leave", False):
                content = member.display_name + " left the voice channel."

        
                audio = await RunTTS(content, before)
                if type(audio) == discord.Embed:
                    await AnnounceError(vc, audio)
                    return

        
                await Speak(vc, audio)
            
        



@client.event
async def on_entitlement_create(entitlement):
    guild = await GetGuild(entitlement.guild)
    debug = client.get_channel(debug_channel_id)
    tier = await db.tiers.find_one({"sku_id": entitlement.sku_id})
    # DURABLE	2	Durable one-time purchase
    # CONSUMABLE	3	Consumable one-time purchase
    # SUBSCRIPTION	5	Represents a recurring subscription
    # SUBSCRIPTION_GROUP	6	System-generated group for each SUBSCRIPTION SKU created
    if tier.get("type") == 5:
        # Subscription
        if tier.get("flags") == 128:
            # guild
            sub = {
                "tier": tier.get("name"),
                "sku_id": entitlement.sku_id,
                "starts_at": entitlement.starts_at,
                "ends_at": entitlement.ends_at
            }
            

            upd = await db.guilds.update_one({"id": entitlement.guild.id}, {"$set": {"subscription": sub, "daily_limit": tier.get("daily_limit")}})
            await debug.send("Subscription created for " + entitlement.guild.name)
            print(upd)


@client.event
async def on_entitlement_update(entitlement):
    user = await GetUser(entitlement.user.id)
    guild = await GetGuild(entitlement.guild)
    debug = client.get_channel(debug_channel_id)
    tier = await db.tiers.find_one({"sku_id": entitlement.sku_id})
    if tier.get("type") == 5:
        # Subscription
        if tier.get("flags") == 128:
            sub = {
                "tier": tier.get("name"),
                "sku_id": entitlement.sku_id,
                "starts_at": entitlement.starts_at,
                "ends_at": entitlement.ends_at
            }
            if guild.get("subscription", {}).get("ends_at") == entitlement.ends_at and guild.get("subscription", {}).get("sku_id") == entitlement.sku_id:
                await db.guilds.update_one({"id": guild["id"]}, {"$set": {"subscription": sub}})
                await debug.send("Subscription cancelled for " + entitlement.guild.name)
                return
            if guild.get("subscription", {}).get("ends_at") < entitlement.ends_at and guild.get("subscription", {}).get("sku_id") == entitlement.sku_id:
                await debug.send("Subscription renewed for " + entitlement.guild.name)
                await db.guilds.update_one({"id": guild["id"]}, {"$set": {"subscription": sub}})
                return


@client.event
async def on_entitlement_delete(entitlement):
    user = await GetUser(entitlement.user.id)
    guild = await GetGuild(entitlement.guild)
    debug = client.get_channel(debug_channel_id)
    if user.get("subscription") and guild.get("subscription", {}).get("sku_id") == entitlement.sku_id:
        await db.guilds.update_one({"id": guild["id"]}, {"$set": {"subscription": None}})
        await debug.send("Subscription refunded/deleted for " + entitlement.guild.name)
        


@tree.error
async def on_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
    embed = await ErrorEmbed(str(error), interaction.id, interaction.user.id, "Unknown Error")
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=embed)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    return

#@client.event
#async def on_error(event, *args, **kwargs):
#    try:
#        print(args)
#        print(args[0].channel.id)
#        embed = await ErrorEmbed("An unknown error occured.", args[0].id, args[0].author.id, "Unknown Error")
#        channel = await client.fetch_channel(args[0].channel.id)
#        await channel.send(embed=embed)
#    except:
#        pass

looptime = datetime.time(hour=0, minute=00)

@tasks.loop(time=looptime) # repeat after every 24 hour
async def DayCapReset():
    print("day")
    await db.users.update_many({"daily_usage": {"$gt": 0}}, {"$set": {"daily_usage": 0}})
    await db.guilds.update_many({"daily_usage": {"$gt": 0}}, {"$set": {"daily_usage": 0}})
  



client.run(DISCORD_TOKEN)
