import os
import re

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

IMAGE_URL_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
)

VIDEO_URL_EXTENSIONS = (
    ".mp4",
    ".mov",
    ".webm",
    ".mkv",
    ".avi",
    ".m3u8",
)


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

    # Common meme misspelling: "hampter"
    return "hampter" in tokens


def is_image_candidate(media_url, content_type, is_video_embed=False):
    """Returns True when media is image-compatible for image_url vision input."""
    if is_video_embed:
        return False

    lowered_url = (media_url or "").lower()
    lowered_content_type = (content_type or "").lower()

    if not lowered_url.startswith(("http://", "https://")):
        return False

    if lowered_content_type.startswith("image/"):
        return True
    if lowered_content_type.startswith("video/"):
        return False

    url_without_query = lowered_url.split("?", 1)[0]
    if url_without_query.endswith(VIDEO_URL_EXTENSIONS):
        return False

    return url_without_query.endswith(IMAGE_URL_EXTENSIONS)


def collect_media_candidates(message):
    """Collect all media URLs and cheap metadata from a Discord message."""
    candidates = []
    seen_urls = set()

    for attachment in message.attachments:
        media_url = attachment.url
        if not media_url or media_url in seen_urls:
            continue

        candidates.append(
            {
                "url": media_url,
                "content_type": attachment.content_type,
                "is_video_embed": False,
                "metadata": [
                    message.content,
                    attachment.filename,
                    attachment.description,
                    attachment.proxy_url,
                    attachment.content_type,
                ],
            }
        )
        seen_urls.add(media_url)

    for embed in message.embeds:
        if embed.type not in ["gifv", "image", "video", "rich"]:
            continue

        media_url = None
        is_video_embed = False
        # Prefer image-like URLs first to avoid sending video links into image_url vision inputs.
        if embed.image:
            media_url = embed.image.url
        elif embed.thumbnail:
            media_url = embed.thumbnail.url
        elif embed.video:
            media_url = embed.video.url
            is_video_embed = True
        elif embed.url:
            media_url = embed.url
            is_video_embed = embed.type == "video"

        if not media_url:
            continue

        if media_url in seen_urls:
            continue

        candidates.append(
            {
                "url": media_url,
                "content_type": None,
                "is_video_embed": is_video_embed,
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
        seen_urls.add(media_url)

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

    # Payload asking the AI to check the image
    payload = {
        "model": "openai/gpt-4o-mini",  # Fast, cheap, and good at vision
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
        # Send request to OpenRouter
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(f"Error from OpenRouter: {resp.status} | {body[:300]}")
                return False

            data = await resp.json()

            try:
                # Dig out the AI's response text
                answer = data["choices"][0]["message"]["content"].strip().upper()
                print(f"AI sees: {answer}")
                first_token = re.sub(r"[^A-Z]", " ", answer).split()
                return bool(first_token) and first_token[0] == "YES"
            except (KeyError, IndexError):
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
        # Message was likely removed by a moderator/bot while we were processing it.
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
    # Ignore messages from the bot itself
    if message.author == client.user or message.author.bot:
        return

    media_candidates = collect_media_candidates(message)

    for candidate in media_candidates:
        media_url = candidate["url"]
        content_type = candidate["content_type"]
        metadata = candidate["metadata"]
        is_video_embed = candidate["is_video_embed"]

        if metadata_indicates_hamster(*metadata):
            print(f"Metadata hit for hamster from {message.author}: {media_url}")
            is_hamster = True
        elif is_image_candidate(media_url, content_type, is_video_embed):
            print(f"Checking image media from {message.author}: {media_url}")
            is_hamster = await analyze_image_for_hamster(media_url)
        else:
            # Avoid paid call + 400s by skipping non-image media in image_url flow.
            print(f"Skipping non-image media from {message.author}: {media_url}")
            is_hamster = False

        if is_hamster:
            deleted = await delete_hamster_message(message)
            if deleted:
                await notify_hamster_deleted(message)
            return


client.run(TOKEN)
