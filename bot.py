import discord
import os
import aiohttp
import re
from dotenv import load_dotenv

# Load the keys from your .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Set up Discord intents (Required to read messages)
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

HAMSTER_KEYWORDS = {
    "hamster",
    "hammy",
    "hamtaro",
}


def _extract_strings(value):
    """Recursively flatten nested metadata into strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        flattened = []
        for nested in value.values():
            flattened.extend(_extract_strings(nested))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened = []
        for nested in value:
            flattened.extend(_extract_strings(nested))
        return flattened
    return [str(value)]


def metadata_indicates_hamster(*parts):
    """Free hamster detection from Discord metadata (filenames, embed text, URLs)."""
    searchable_text = " ".join(_extract_strings(parts)).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", searchable_text)
    tokens = set(normalized.split())

    if any(keyword in searchable_text for keyword in HAMSTER_KEYWORDS):
        return True

    return "hampter" in tokens


def collect_media_candidates(message):
    """Collect all media URLs and cheap metadata from a Discord message."""
    candidates = []

    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith(('image/', 'video/')):
            candidates.append(
                {
                    "url": attachment.url,
                    "metadata": [
                        message.content,
                        attachment.filename,
                        attachment.description,
                        attachment.proxy_url,
                        attachment.content_type,
                    ],
                }
            )

    for embed in message.embeds:
        if embed.type in ['gifv', 'image', 'video', 'rich']:
            media_url = None
            if embed.video:
                media_url = embed.video.url
            elif embed.image:
                media_url = embed.image.url
            elif embed.thumbnail:
                media_url = embed.thumbnail.url
            elif embed.url:
                media_url = embed.url

            if media_url:
                candidates.append(
                    {
                        "url": media_url,
                        "metadata": [
                            message.content,
                            embed.title,
                            embed.description,
                            embed.url,
                            embed.type,
                            embed.provider.name if embed.provider else None,
                            embed.author.name if embed.author else None,
                            embed.footer.text if embed.footer else None,
                            embed.to_dict(),
                        ],
                    }
                )

    return candidates

async def analyze_image_for_hamster(image_url):
    """Sends the image URL to OpenRouter's vision model."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Payload asking the AI to check the image
    payload = {
        "model": "openai/gpt-4o-mini", # Fast, cheap, and good at vision
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
    
    async with aiohttp.ClientSession() as session:
        # Send request to OpenRouter
        async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload) as resp:
            if resp.status != 200:
                print(f"Error from OpenRouter: {resp.status}")
                return False
            
            data = await resp.json()
            
            try:
                # Dig out the AI's response text
                answer = data['choices'][0]['message']['content'].strip().upper()
                print(f"AI sees: {answer}")
                return "YES" in answer
            except (KeyError, IndexError):
                print("Failed to parse AI response.")
                return False

@client.event
async def on_ready():
    print(f'Logged in as {client.user} - Ready to terminate hamsters.')

@client.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == client.user:
        return

    media_candidates = collect_media_candidates(message)

    for candidate in media_candidates:
        image_url_to_check = candidate["url"]
        metadata = candidate["metadata"]

        if metadata_indicates_hamster(*metadata):
            print(f"Metadata hit for hamster from {message.author}: {image_url_to_check}")
            is_hamster = True
        else:
            print(f"Checking media from {message.author}: {image_url_to_check}")
            is_hamster = await analyze_image_for_hamster(image_url_to_check)

        if is_hamster:
            try:
                await message.delete()
                await message.channel.send(f"🚨 {message.author.mention}, hamster detected and deleted! 🚨")
                return
            except discord.Forbidden:
                print("Error: Bot doesn't have permission to delete messages in this channel.")
                return

client.run(TOKEN)
