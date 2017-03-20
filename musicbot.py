import asyncio
import discord
import requests
import os
from datetime import datetime, timezone, timedelta
import config
## youtube api key and mail
## 
key = config.key
## add the token from your app dashboard on discord dev site
token = config.token
import json
from discord.ext import commands

if not discord.opus.is_loaded():
    # the 'opus' library here is opus.dll on windows
    # or libopus.so on linux in the current directory
    # you should replace this with the location the
    # opus library is located in and with the proper filename.
    # note that on windows this DLL is automatically provided for you
    discord.opus.load_opus('opus')
    print("opus loaded")

class VoiceEntry:
    def __init__(self, message, player):
        self.requester = message.author
        self.channel = message.channel
        self.player = player

    def __str__(self):
        fmt = '*{0.title}* uploaded by {0.uploader} and requested by {1.display_name}'
        duration = self.player.duration
        if duration:
            fmt = fmt + ' [length: {0[0]}m {0[1]}s]'.format(divmod(duration, 60))
        return fmt.format(self.player, self.requester)

class VoiceState:
    def __init__(self, bot):
        self.current = None
        self.voice = None
        self.bot = bot
        self.play_next_song = asyncio.Event()
        self.songs = asyncio.Queue()
        self.skip_votes = set() # a set of user_ids that voted
        self.audio_player = self.bot.loop.create_task(self.audio_player_task())

    def is_playing(self):
        if self.voice is None or self.current is None:
            return False

        player = self.current.player
        return not player.is_done()

    @property
    def player(self):
        return self.current.player

    def skip(self):
        self.skip_votes.clear()
        if self.is_playing():
            self.player.stop()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    async def audio_player_task(self):
        while True:
            self.play_next_song.clear()
            self.current = await self.songs.get()
            await self.bot.send_message(self.current.channel, 'Now playing ' + str(self.current))
            self.current.player.start()
            await self.play_next_song.wait()


class Music:
    """Voice related commands.
    Works in multiple servers at once.
    """
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, server):
        state = self.voice_states.get(server.id)
        if state is None:
            state = VoiceState(self.bot)
            self.voice_states[server.id] = state

        return state

    async def create_voice_client(self, channel):
        voice = await self.bot.join_voice_channel(channel)
        state = self.get_voice_state(channel.server)
        state.voice = voice

    def __unload(self):
        for state in self.voice_states.values():
            try:
                state.audio_player.cancel()
                if state.voice:
                    self.bot.loop.create_task(state.voice.disconnect())
            except:
                pass

    @commands.command(pass_context=True, no_pm=True)
    async def join(self, ctx, *, channel : discord.Channel):
        """Joins a voice channel."""
        try:
            await self.create_voice_client(channel)
        except discord.ClientException:
            await self.bot.say('Already in a voice channel...')
        except discord.InvalidArgument:
            await self.bot.say('This is not a voice channel...')
        else:
            await self.bot.say('Ready to play audio in ' + channel.name)

    @commands.command(pass_context=True, no_pm=True)
    async def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        summoned_channel = ctx.message.author.voice_channel
        if summoned_channel is None:
            await self.bot.say('You are not in a voice channel.')
            return False

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            state.voice = await self.bot.join_voice_channel(summoned_channel)
        else:
            await state.voice.move_to(summoned_channel)

        return True

    

    @commands.command(pass_context=True, no_pm=True)
    async def play(self, ctx, *, song : str):
        """Plays a song.
        If there is a song currently in the queue, then it is
        queued until the next song is done playing.
        This command automatically searches as well from YouTube.
        The list of supported sites can be found here:
        https://rg3.github.io/youtube-dl/supportedsites.html
        """
        state = self.get_voice_state(ctx.message.server)
        opts = {
            'default_search': 'auto',
            'quiet': True,
        }

        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        try:
            player = await state.voice.create_ytdl_player(song, ytdl_options=opts, after=state.toggle_next)
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        else:
            player.volume = 0.6
            entry = VoiceEntry(ctx.message, player)
            await self.bot.say('Enqueued ' + str(entry))
            await state.songs.put(entry)


    @commands.command(pass_context=True, no_pm=True)
    async def volume(self, ctx, value : int):
        """Sets the volume of the currently playing song."""

        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.volume = value / 100
            await self.bot.say('Set the volume to {:.0%}'.format(player.volume))

    @commands.command(pass_context=True, no_pm=True)
    async def pause(self, ctx):
        """Pauses the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.pause()

    @commands.command(pass_context=True, no_pm=True)
    async def resume(self, ctx):
        """Resumes the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.resume()

    @commands.command(pass_context=True, no_pm=True)
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        server = ctx.message.server
        state = self.get_voice_state(server)

        if state.is_playing():
            player = state.player
            player.stop()

        try:
            state.audio_player.cancel()
            del self.voice_states[server.id]
            await state.voice.disconnect()
        except:
            pass

    @commands.command(pass_context=True, no_pm=True)
    async def skip(self, ctx):
        """Vote to skip a song. The song requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        state = self.get_voice_state(ctx.message.server)
        if not state.is_playing():
            await self.bot.say('Not playing any music right now...')
            return

        voter = ctx.message.author
        if voter == state.current.requester:
            await self.bot.say('Requester requested skipping song...')
            state.skip()
        elif voter.id not in state.skip_votes:
            state.skip_votes.add(voter.id)
            total_votes = len(state.skip_votes)
            if total_votes >= 3:
                await self.bot.say('Skip vote passed, skipping song...')
                state.skip()
            else:
                await self.bot.say('Skip vote added, currently at [{}/3]'.format(total_votes))
        else:
            await self.bot.say('You have already voted to skip this song.')

    @commands.command(pass_context=True, no_pm=True)
    async def playing(self, ctx):
        """Shows info about the currently played song."""

        state = self.get_voice_state(ctx.message.server)
        if state.current is None:
            await self.bot.say('Not playing anything.')
        else:
            skip_count = len(state.skip_votes)
            await self.bot.say('Now playing {} [skips: {}/3]'.format(state.current, skip_count))

class Maester:
    """try say hi """
    def __init__(self,bot):
        self.bot = bot
        """insert your discord id here in order to be recognized as the Master"""
        self.masterid= '98468362559950848'

    @commands.command(pass_context = True, no_pm = True)
    async def hi(self,ctx):
        if ctx.message.author.id == self.masterid:
            await self.bot.say('I greet my master')
            await self.bot.say('http://i.imgur.com/VZwh5Bg.png')
        else:
            await self.bot.say("I don't have time to listen to you, pleb")

class simcraft:
    """
    Install simulationcraft addon. Feed the result from SimC addon to !loadchar, then !simc for obtaining 
    the result. Beware very CPU intensive.
    """
    def __init__(self,bot):
        self.bot = bot

    @commands.command(pass_context = True, no_pm = True)
    async def simc(self,ctx):
        """Load a character string. Copy the string from SimC addon"""
        self.filename = ctx.message.author.id + '.txt'
        self.f = open(filename,'r')
        self.instru=[]
        for self.r in self.f:
            self.instru = self.instru + ' ' + r
        """
        in os.system replace 'simc.exe' with the path to Simulationcraft executable. 
        """ 
        os.system('simc.exe ' + self.instru + '> ' + 'output' + self.filename)
        self.f.close()
        self.f = open('output' + filename,'r')
        for self.r in self.f:
            if self.r.split()[0] == 'DPS:':
                await self.bot.say(self.r)
        self.f.close()


    @commands.command(pass_context = True, no_pm = True)
    async def loadchar(self,ctx, *, simcstr : str):
        """Fire the simulation! (works only after loading the string with !loadchar)"""
        self.filename = ctx.message.author.id + '.txt'
        self.f = open(filename,'w')
        f.write(simcstr)
        self.f.close()

class YT:
    """
    Two useful commands for searching youtube videos.
    """
    def __init__(self,bot):
        self.bot =bot 

    @commands.command(pass_context=True, no_pm=True)
    async def lastvideo(self,ctx, *, name : str):
        """ Last video from a channel """
        name = name.split()[0] # first word after command
        if name: #check if the channel name is provided
            user = requests.get('https://www.googleapis.com/youtube/v3/search?part=snippet&q='+ name +'&key='+ key ) #YT search
            jsuser = user.json()
        if jsuser["items"]:
            channelid = jsuser["items"][0]["snippet"]["channelId"]
            lastvideo = requests.get ( 'https://www.googleapis.com/youtube/v3/search?key='+ key +'&channelId=' + channelid +'&part=snippet,id&order=date&maxResults=5')
            jslastvideo = lastvideo.json()
            cc=0
            lungh = len(jslastvideo['items'])
            while (jslastvideo["items"][cc]["id"]["kind"] != "youtube#video") & (cc <= lungh-1): #if the last id is a channelid there is no last video
                cc=cc+1
            if cc < lungh-1:
                videoidd =  jslastvideo["items"][cc]["id"]["videoId"]
                urllastvideo= 'https://www.youtube.com/watch?v=' + videoidd
                await self.bot.say(urllastvideo)
                return
            if  jslastvideo["items"][cc]["id"]["kind"] == "youtube#video":
                videoidd =  jslastvideo["items"][cc]["id"]["videoId"]
                urllastvideo= 'https://www.youtube.com/watch?v=' + videoidd
                await self.bot.say(urllastvideo)
                
            else:   
                await self.bot.say("All I see it's fog") #quote of an italian comedy 'fog everywhere'
    
    @commands.command(pass_context=True, no_pm=True)
    async def discovery(self,ctx,*,game : str):
        """
        Five videos published in the last 24h in italian
        """
        if game:
            d= datetime.utcnow()
            delta24 = timedelta(hours=-24)
            d = d+delta24
            d= d.isoformat() +'Z'
            """
            Replace the regioncode to modify the priority on the language in the search
            """
            ls = requests.get('https://www.googleapis.com/youtube/v3/search?part=snippet&publishedAfter=' + d +'&q='+ game +'&regionCode=it&relevanceLanguage=it&key='+ key )
            jsls = ls.json()
            count=0
            for i in jsls["items"]:
                if jsls["items"][count]["id"]["videoId"]:
                    videoid = jsls["items"][count]["id"]["videoId"]
                    urlvideo = 'https://www.youtube.com/watch?v=' + videoid
                    await self.bot.say(urlvideo)
                count = count+1
            else:
                return
            

class Scrim:
    """
    Create a Scrim text channel. For convenience an host should be added with the command !host battletag#12345.
    The host is in charge of creating the custom game. Join one team with !pcw 1 or !pcw 2. 
    Play Fair!
    Preconf. for Overwatch 6v6.
    """
    def __init__(self,bot):
        self.bot= bot
        self.pcw1 =[]
        self.pcw2 =[]
        self.lista1 = ''
        self.lista2 = ''
        self.leader =''
        self.skipvote =0
        self.skiplist = []
    
    def lists(self):
        self.lista1 =''
        self.lista2 =''
        for a in self.pcw2:
            self.lista2 = self.lista2 + ' ' + a.mention + ' '
        for a in self.pcw1:
            self.lista1 = self.lista1 + ' ' + a.mention + ' '

    async def printlists(self):
        try:
            await self.bot.say('Team 1: ' + self.lista1 + ' Team 2: ' + self.lista2)
            await self.bot.say('Host:' + self.leader)
        except:
            return
    async def finalprint(self):
        await self.bot.say('Host bnet: ' + self.leader +  ' --  Final teams -- Team 1: ' + self.lista1 + ' Team 2: ' + self.lista2)
        await self.bot.say('Team 1 join pug 1 and Team 2 join pug 2 GL&HF')
        self.pcw1=[]
        self.pcw2=[]
        self.leader=''
        self.skipvote = 0
        self.skiplist =[]






    @commands.command(pass_context = True, no_pm = True)
    async def pcw(self,ctx,*, team : str):
        if ctx.message.channel.name =='scrims':

            print(len(self.pcw1) + len(self.pcw2) )
            if len(self.pcw1) + len(self.pcw2) == 12:
                if self.leader:
                    await self.finalprint()
                    return
                else:
                    await self.bot.say('Decide an host with $host and you are ready to go!')
                    return

            if team == '1' and len(self.pcw1) < 6 and ctx.message.author not in self.pcw1 + self.pcw2:
                self.pcw1.append(ctx.message.author)
                self.lists()
                await self.printlists()
            if team == '2' and len(self.pcw2) <6 and ctx.message.author not in self.pcw1 + self.pcw2:
                self.pcw2.append(ctx.message.author)
                self.lists()
                await self.printlists()

    @commands.command(pass_context = True, no_pm = True)
    async def host(self,ctx,*, bnet : str):
        if ctx.message.channel.name == 'scrims':
            if not self.leader and ctx.message.author in self.pcw1 + self.pcw2:
                self.leader = bnet
                await self.bot.say( ctx.message.author.mention + ' is our leader MrDestructoid. He will create the custom game. Bnet tag: ' + bnet )
            if len(self.pcw1) + len(self.pcw2) == 12 and self.leader:
                await self.finalprint()
                return 

    @commands.command(pass_context = True, no_pm = True)
    async def removeme(self,ctx):
        if ctx.message.channel.name =='scrims' and ctx.message.author in self.pcw1 + self.pcw2:
            try:
                self.pcw1.remove(ctx.message.author)
                self.lists()
                await self.bot.say(ctx.message.author.mention + ' removed!')
                await self.printlists()
            except:
                self.pcw2.remove(ctx.message.author)
                self.lists()
                await self.bot.say(ctx.message.author.mention + ' removed!')
                await self.printlists()


    @commands.command(pass_context = True, no_pm = True)
    async def pcwskip(self, ctx):
        if any([self.pcw1, self.pcw2]) and ctx.message.author not in self.skiplist: 
            self.skipvote = self.skipvote+1
            self.skiplist.append(ctx.message.author)
            await self.bot.say(ctx.message.author.name + ' voted for skip! ' + str (3 - self.skipvote) + ' more vote(s) to skip')
        if (self.skipvote > 2 ):
            await self.bot.say('Scrim purged, add yourself again!')
            self.skipvote = 0
            self.skiplist = []
            self.pcw1=[]
            self.pcw2=[]
            self.lists()
            self.leader=''

    @commands.command(pass_context = True, no_pm = True)
    async def swapme(self,ctx):
        if ctx.message.channel.name =='scrims' and ctx.message.author in self.pcw1 + self.pcw2:
            try:
                self.pcw1.remove(ctx.message.author)
                self.pcw2.append(ctx.message.author)
                self.lists()
                await self.bot.say(ctx.message.author.mention + ' swapped team')
                await self.printlists()               
            except:
                self.pcw2.remove(ctx.message.author)
                self.pcw1.append(ctx.message.author)
                self.lists()
                await self.bot.say(ctx.message.author.mention + ' swapped team')
                await self.printlists()

    @commands.command(pass_context = True, no_pm = True)
    async def state(self,ctx):
        if ctx.message.channel.name =='scrims' and ctx.message.author in self.pcw1 + self.pcw2:
           await self.printlists()
           






"""
decide here what modules you want loaded.
"""
bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), description='ZZbot multipurpose bot for Discord!')
bot.add_cog(Music(bot))
bot.add_cog(Maester(bot))
bot.add_cog(simcraft(bot))
bot.add_cog(YT(bot))
bot.add_cog(Scrim(bot))



@bot.event
async def on_ready():
    print('Logged in as:\n{0} (ID: {0.id})'.format(bot.user))

bot.run(token)