import os
import re
from urllib.parse import urlparse

import aiohttp
import discord
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

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".mpeg", ".mpg"}


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


def infer_media_type(url, content_type=None):
    """Infer media type so we don't send non-image URLs to image-only vision APIs."""
    if content_type:
        normalized = content_type.lower()
        if normalized.startswith("image/"):
            return "image"
        if normalized.startswith("video/"):
            return "video"

    path = urlparse(url).path.lower()
    for extension in IMAGE_EXTENSIONS:
        if path.endswith(extension):
            return "image"
    for extension in VIDEO_EXTENSIONS:
        if path.endswith(extension):
            return "video"

    return "unknown"


def collect_media_candidates(message):
    """Collect all media URLs and cheap metadata from a Discord message."""
    candidates = []

    for attachment in message.attachments:
        media_type = infer_media_type(attachment.url, attachment.content_type)
        if media_type in {"image", "video"}:
            candidates.append(
                {
                    "url": attachment.url,
                    "media_type": media_type,
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
        if embed.type in ["gifv", "image", "video", "rich"]:
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
                if embed.video or embed.type == "gifv":
                    media_type = "video"
                elif embed.image or embed.type == "image":
                    media_type = "image"
                else:
                    media_type = infer_media_type(media_url)
                candidates.append(
                    {
                        "url": media_url,
                        "media_type": media_type,
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
    if not OPENROUTER_API_KEY:
        print("Error: OPENROUTER_API_KEY is missing; skipping vision check.")
        return False

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Determine if there is a hamster in this image. This includes real, cartoon, anime, or highly stylized anthropomorphic characters. Look closely for specific visual cues like small, circular ears, a round body shape, or classic hamster color patches. Answer strictly with one word: YES or NO.",
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                print(f"Error from OpenRouter: status={resp.status}, body={error_text}")
                return False

            data = await resp.json()

            try:
                answer = data["choices"][0]["message"]["content"].strip().upper()
                print(f"AI sees: {answer}")
                first_token = re.sub(r"[^A-Z]", " ", answer).split()
                return bool(first_token) and first_token[0] == "YES"
            except (KeyError, IndexError, TypeError, AttributeError):
                print("Failed to parse AI response.")
                return False


async def delete_hamster_message(message):
    """Delete detected hamster message with clear failure reasons."""
    try:
        await message.delete()
        return True
    except discord.Forbidden as exc:
        print(
            "Error: Missing permission to delete message "
            f"in #{message.channel} ({message.guild}): {exc}"
        )
    except discord.NotFound:
        print("Message already deleted before bot action completed.")
    except discord.HTTPException as exc:
        print(f"Discord API error while deleting message: {exc}")

    return False


async def notify_hamster_deleted(message):
    """Send user feedback after deletion without masking delete success."""
    try:
        await message.channel.send(f"🚨 {message.author.mention}, hamster detected and deleted! 🚨")
    except discord.Forbidden as exc:
        print(f"Deleted message but cannot send confirmation in this channel: {exc}")
    except discord.HTTPException as exc:
        print(f"Deleted message but failed to send confirmation: {exc}")


@client.event
async def on_ready():
    print(f"Logged in as {client.user} - Ready to terminate hamsters.")


@client.event
async def on_message(message):
    if message.author == client.user or message.author.bot:
        return

    media_candidates = collect_media_candidates(message)

    for candidate in media_candidates:
        media_url_to_check = candidate["url"]
        media_type = candidate["media_type"]
        metadata = candidate["metadata"]

        if metadata_indicates_hamster(*metadata):
            print(f"Metadata hit for hamster from {message.author}: {media_url_to_check}")
            is_hamster = True
        elif media_type != "image":
            print(
                f"Skipping non-image media from {message.author}: "
                f"{media_url_to_check} (type={media_type})"
            )
            is_hamster = False
        else:
            print(f"Checking image from {message.author}: {media_url_to_check}")
            is_hamster = await analyze_image_for_hamster(media_url_to_check)

        if is_hamster:
            deleted = await delete_hamster_message(message)
            if deleted:
                await notify_hamster_deleted(message)
            return


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Set it in the environment or .env file.")
    client.run(TOKEN)
