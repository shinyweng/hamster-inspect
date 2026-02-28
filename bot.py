import discord
import os
import aiohttp
import asyncio
from dotenv import load_dotenv

# Load the keys from your .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Sanity checks for missing or empty secrets
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set or empty. Please add it to your .env file.")
if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY is not set or empty. Please add it to your .env file.")

async def analyze_image_for_hamster(session: aiohttp.ClientSession, image_url: str) -> bool:
    """Sends the public Discord image URL directly to OpenRouter's vision model."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    # 1. Prepare the payload with the URL natively
    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Determine if there is a hamster in this image. This includes real, cartoon, anime, or highly stylized anthropomorphic characters. Look closely for specific visual cues like small, circular ears, a round body shape, or classic hamster color patches. Answer strictly with one word: YES or NO."},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]
    }
    
    try:
        # 2. Send the request to OpenRouter with a 15-second timeout
        async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                print(f"Error from OpenRouter: status={resp.status}, body={error_text}")
                return False
            
            data = await resp.json()
            
            # 3. Safely parse the AI's response
            answer = data['choices'][0]['message']['content'].strip().upper()
            print(f"AI sees: {answer}")
            return "YES" in answer

    except asyncio.TimeoutError:
        print("Timeout: Contacting OpenRouter took too long.")
        return False
    except aiohttp.ClientError as e:
        print(f"Network error occurred: {e}")
        return False
    except (KeyError, IndexError) as e:
        print(f"Failed to parse AI response. Missing expected data fields: {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during image analysis: {e}")
        return False


class HamsterBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = None # Placeholder for our web session
        self.forbidden_words = ["hamster", "hamtaro", "hammy", "ebichu", "hampter"]

    async def setup_hook(self):
        # Initialize the session once when the bot starts
        self.session = aiohttp.ClientSession()

    async def close(self):
        # Clean up the session safely when the bot shuts down
        if self.session:
            await self.session.close()
        await super().close()

    async def on_ready(self):
        print(f'Logged in as {self.user} - Ready to terminate hamsters.')

    async def _delete_and_warn(self, message):
        """Helper method to handle deletions safely and keep code DRY."""
        try:
            warning_text = (
                "🚨 Good bye Andrew's Hamsters. 🚨" 
                if message.author.name == 'andreww4444' 
                else f"🚨 {message.author.mention}, hamster detected and deleted! 🚨"
            )
            await message.delete()
            await message.channel.send(warning_text)
        except discord.Forbidden:
            print("Error: Bot doesn't have permission to delete messages in this channel.")
        except discord.NotFound:
            print("Warning: message could not be deleted (not found or already deleted).")

    async def on_message_edit(self, before, after):
        """Catches delayed embeds (like pasted Tenor/Giphy links) that unfurl after sending."""
        if not before.embeds and after.embeds:
            await self.on_message(after)

    async def on_message(self, message):
        # Ignore messages from the bot itself
        if message.author == self.user:
            return

        # 1. Fast-Path: Check the actual message text first
        text_lower = message.content.lower()
        if text_lower.startswith(('http://', 'https://')) and any(word in text_lower for word in self.forbidden_words):
            print(f"Message text triggered deletion: {message.author}, {text_lower}")
            await self._delete_and_warn(message)
            return

        # 2. Collect ALL potential image URLs to prevent the "Trojan Hamster" exploit
        urls_to_check = []

        # Attachments
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                urls_to_check.append(attachment.url)

        # Embeds
        for embed in message.embeds:
            if embed.type in ['gifv', 'image']:
                url = embed.thumbnail.url if embed.thumbnail else embed.url
                if url:
                    urls_to_check.append(url)

        # 3. Process the collected URLs
        for url in urls_to_check:
            url_lower = url.lower()
            
            # Fast-Path: Check the URL string itself
            if any(word in url_lower for word in self.forbidden_words):
                print(f"URL string triggered deletion: {url}")
                await self._delete_and_warn(message)
                return # Stop looping, message is already gone
                
            # Slow-Path: Send to the Vision AI
            print(f"URL seems clean, scanning image pixels from {message.author}...")
            is_hamster = await analyze_image_for_hamster(self.session, url)

            # 4. Execute the deletion if AI detects a hamster
            if is_hamster:
                await self._delete_and_warn(message)
                return # Stop looping through remaining images, message is gone


# Set up Discord intents
intents = discord.Intents.default()
intents.message_content = True

# Initialize and run the bot
client = HamsterBot(intents=intents)

if __name__ == "__main__":
    client.run(TOKEN)