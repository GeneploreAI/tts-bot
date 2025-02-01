# An experimental Text-to-Speech Discord bot
This Discord bot was an experiment with the OpenAI TTS API, where users would be able to join voice channels and hear messages sent in specified text channel. The bot also included a few other commands related to TTS functions, like `/tts [text]` which would generate speech from a given prompt using the OpenAI or Google APIs.

## Getting Started

1. Create a bot at https://discord.dev/ and get a Bot Token.
2. Install Python 3.12.2, create a `venv`, and install the dependencies listed at `requirements.txt`.
3. Initialize a MongoDB database using either MongoDB Atlas or another suitable cloud/local platform.
4. Get an OpenAI API key at https://platform.openai.com
5. (optional) Get Google Cloud Application Default Credentials (ADC) and load it into your working environment. Running this bot in a Google Compute Engine VM is recommended.
6. Create a `.env` file with the three secrets you have acquired listed as so:

```
OPENAI_API_KEY=sk-...
DISCORD_TOKEN=MTI...
MONGODB_URL==mongodb+srv://...
```
7. Update the `client.user.id` and following IDs at line 55 to match your environment.
8. Replace line 1239's user snowflake with your own Discord snowflake, so you can sync the bot's commands.
9. Activate the `venv` and run `python main.py` to initialize the bot.
10. Add the bot to your server with a provided OAuth 2 URL back at https://discord.dev
11. DM the bot `!sync` to sync the command tree with the Discord API.

Developed by Geneplore AI

https://geneplore.com