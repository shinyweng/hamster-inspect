import discord
import os
import aiohttp
import asyncio
from dotenv import load_dotenv

# Load the keys from your .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not TOKEN or not OPENROUTER_API_KEY:
    raise RuntimeError("Missing DISCORD_TOKEN or OPENROUTER_API_KEY in .env file.")

class GrokSummarizer(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = None # Placeholder for our aiohttp web session
        self.grok_role_id = "1467201281746796729" # Stored for easy access

    async def setup_hook(self):
        # Initialize the session once when the bot starts
        self.session = aiohttp.ClientSession()

    async def close(self):
        # Clean up the session safely when the bot shuts down
        if self.session:
            await self.session.close()
        await super().close()

    async def on_ready(self):
        print(f'✅ Logged in as {self.user} - Ready to assist with Grok!')

    async def fetch_grok_response(self, chat_log: str, user_prompt: str = None) -> str:
        """Sends the compiled chat history and optional user prompt to OpenRouter."""
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Determine the system and user instructions based on the presence of a user_prompt
        if user_prompt:
            system_instruction = "Accurately answer the user's prompt in 1-3 sentences, concisely."
            user_content = f"User's prompt: {user_prompt}"
        else:
            system_instruction = "Read the following chat history and provide a concise, readable summary of the conversation. Focus on the main topics and any conclusions reached in 3 sentences max."
            user_content = f"Here is the recent chat history:\n\n{chat_log}"

        payload = {
            "model": "openai/gpt-4o-mini", 
            "messages": [
                {
                    "role": "system", 
                    "content": system_instruction
                },
                {
                    "role": "user", 
                    "content": user_content
                }
            ]
        }

        try:
            # Send the request to OpenRouter with a 15-second timeout
            async with self.session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"Error from OpenRouter: status={resp.status}, body={error_text}")
                    return "⚠️ Sorry, I ran into an API error while trying to process that."
                
                data = await resp.json()
                return data['choices'][0]['message']['content'].strip()

        except asyncio.TimeoutError:
            return "⚠️ Grok took too long to respond. Please try again later."
        except Exception as e:
            print(f"Unexpected error: {e}")
            return "⚠️ An unexpected error occurred while contacting Grok."

    async def on_message(self, message):
        # Ignore messages from the bot itself
        if message.author == self.user:
            return
        
        # Check if the specific role was mentioned
        grok_role_mentioned = any(role.id == int(self.grok_role_id) for role in message.role_mentions)
        
        if grok_role_mentioned:
            # Extract any text sent alongside the tag
            clean_prompt = message.content.replace(f"<@&{self.grok_role_id}>", "").strip()
            
            # Send an appropriate loading message
            if not clean_prompt:
                loading_msg = await message.channel.send("Reading the last 30 messages... ⏳")
            else:
                loading_msg = await message.channel.send("Thinking... ⏳")

            try:
                # 1. Fetch the last 31 messages (30 history + the trigger message itself)
                messages = [msg async for msg in message.channel.history(limit=31)]
                messages.reverse() # Reverse so they read chronologically (oldest to newest)

                # 2. Format the chat history into a string
                chat_log = ""
                # Use [:-1] to exclude the command message that just triggered the bot
                for msg in messages[:-1]: 
                    # Skip empty messages (like images with no text) to save tokens
                    if msg.content.strip():
                        chat_log += f"[{msg.author.display_name}]: {msg.content}\n"

                # 3. Check if there's actually anything to read
                if not chat_log.strip():
                    await loading_msg.edit(content="There is no recent text history here.")
                    return

                # 4. Call the AI
                response = await self.fetch_grok_response(chat_log, user_prompt=clean_prompt if clean_prompt else None)

                # 5. Edit the loading message with the final result
                if not clean_prompt:
                    await loading_msg.edit(content=f"**Grok's Summary:**\n\n{response}")
                else:
                    await loading_msg.edit(content=f"**Grok:** {response}")

            except discord.Forbidden:
                await loading_msg.edit(content="⚠️ I don't have permission to read message history in this channel.")
            except Exception as e:
                print(f"Error fetching history: {e}")
                await loading_msg.edit(content="⚠️ Something went wrong while reading the channel history.")

# Set up Discord intents
intents = discord.Intents.default()
intents.message_content = True # Required to read what users say!

# Initialize and run the bot
client = GrokSummarizer(intents=intents)

if __name__ == "__main__":
    client.run(TOKEN)