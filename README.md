# multipurpose-zzbot
A discordapp bot 

<h1> ZZbot </h1> 
A bot for discord written in Python3. It features some youtube search functionalities (retrieving last video from a channel, discovering
videos published in the past 24h in a specified language), a matchmaking feature for team games (currently preconfigured for
Overwatch 6v6), an integrated World of Warcraft character simulator which uses <a href="https://www.simulationcraft.org/"> SimulationCraft </a>

<h1> Setup </h1>
Requires Python 3

```sh
python -m pip install requirements.txt
```

Check <a href="https://github.com/Rapptz/discord.py"> discord.py page </a> and follow the instructions for installing voice. 
Install the latest version of SimulationCraft from <a href="https://www.simulationcraft.org/"> SimulationCraft </a> and update the path in 

```python
Class simcraft:
...
```

<h1> Credits </h1>

The music module is taken from discord.py  <a href="https://github.com/Rapptz/discord.py/blob/async/examples/playlist.py">example</a>
