import os
import re
import tempfile
from pathlib import Path

import yt_dlp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

ALLOWED_DOMAINS = (
    "instagram.com",
    "www.instagram.com",
    "tiktok.com",
    "www.tiktok.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
)


def is_supported_url(text: str) -> bool:
    text = text.lower().strip()
    return any(domain in text for domain in ALLOWED_DOMAINS)


def get_url(text: str) -> str | None:
    match = re.search(r"https?://\S+", text)
    if not match:
        return None

    url = match.group(0).rstrip(".,!?)]}")
    return url


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "Instagram, TikTok yoki YouTube videosining havolasini yuboring.\n\n"
        "🤖 UmarDownloadBot"
    )


async def download_video(url: str, folder: str) -> Path | None:
    output_template = str(Path(folder) / "video.%(ext)s")

    options = {
        "outtmpl": output_template,
        "format": "best[ext=mp4][vcodec!=none]/best[vcodec!=none]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "socket_timeout": 30,
        "retries": 2,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except Exception:
        return None

    files = list(Path(folder).glob("video.*"))

    if not files:
        return None

    return files[0]


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    url = get_url(text)

    if not url or not is_supported_url(url):
        return

    with tempfile.TemporaryDirectory() as temp_folder:
        video = await download_video(url, temp_folder)

        if video is None or not video.exists():
            await update.message.reply_text(
                "❌ Videoni yuklab bo‘lmadi.\n"
                "Havola ochiq va ishlaydigan bo‘lishi kerak."
            )
            return

        try:
            with open(video, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    supports_streaming=True,
                    caption="🤖 @UmarDownloadBot",
                )
        except Exception:
            try:
                with open(video, "rb") as video_file:
                    await update.message.reply_document(
                        document=video_file,
                        caption="🤖 @UmarDownloadBot",
                    )
            except Exception:
                await update.message.reply_text(
                    "❌ Videoni yuborishda xatolik yuz berdi."
                )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN topilmadi")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
