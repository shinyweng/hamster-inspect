import discord
import os
import aiohttp
from dotenv import load_dotenv

# Load the keys from your .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Set up Discord intents (Required to read messages)
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

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
                    {"type": "text", "text": "Is there a hamster (hamtaro included) in this image? Answer strictly with one word: YES or NO."},
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

    image_url_to_check = None

    # 1. Check for uploaded attachments (Files from computer/phone)
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith(('image/', 'video/')):
            image_url_to_check = attachment.url
            break # Found one, stop looking

    # 2. Check for Embeds (Discord's built-in GIF button / pasted links)
    if not image_url_to_check:
        for embed in message.embeds:
            if embed.type in ['gifv', 'image']:
                # Grab the actual image URL from the embed
                image_url_to_check = embed.thumbnail.url if embed.thumbnail else embed.url
                break

    # If we found an image or GIF, send it to the AI
    if image_url_to_check:
        print(f"Checking image from {message.author}...")
        is_hamster = await analyze_image_for_hamster(image_url_to_check)
        
        if is_hamster:
            try:
                await message.delete()
                await message.channel.send(f"🚨 {message.author.mention}, hamster detected and deleted! 🚨")
            except discord.Forbidden:
                print("Error: Bot doesn't have permission to delete messages in this channel.")

client.run(TOKEN)