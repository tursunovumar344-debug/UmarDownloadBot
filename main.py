import os
import re
import tempfile
import threading
import http.server
import asyncio
from pathlib import Path

import yt_dlp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


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


def get_url(text):
    match = re.search(r"https?://\S+", text)

    if not match:
        return None

    return match.group(0).rstrip(".,!?)]}")


def is_supported(url):
    url = url.lower()

    for domain in ALLOWED_DOMAINS:
        if domain in url:
            return True

    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "Instagram, TikTok yoki YouTube havolasini yuboring.\n\n"
        "🤖 @UmarDownloadBot"
    )


def download_video_sync(url, folder):
    output = str(Path(folder) / "video.%(ext)s")

    options = {
        "outtmpl": output,
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "retries": 3,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

    except Exception as error:
        print("DOWNLOAD ERROR:", error)
        return None

    files = list(Path(folder).glob("video.*"))

    files = [
        file for file in files
        if file.is_file()
        and file.stat().st_size > 0
        and not file.name.endswith(".part")
    ]

    if not files:
        return None

    files.sort(
        key=lambda file: file.stat().st_size,
        reverse=True
    )

    return files[0]


async def download_video(url, folder):
    return await asyncio.to_thread(
        download_video_sync,
        url,
        folder
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    if not update.message.text:
        return

    text = update.message.text.strip()

    url = get_url(text)

    if not url:
        return

    if not is_supported(url):
        await update.message.reply_text(
            "❌ Bu havola qo‘llab-quvvatlanmaydi.\n\n"
            "Instagram, TikTok yoki YouTube havolasini yuboring."
        )
        return

    loading = await update.message.reply_text(
        "⏳ Yuklanmoqda..."
    )

    with tempfile.TemporaryDirectory() as folder:

        video = await download_video(url, folder)

        if video is None or not video.exists():

            try:
                await loading.edit_text(
                    "❌ Videoni yuklab bo‘lmadi."
                )
            except Exception:
                pass

            return

        try:
            await loading.delete()
        except Exception:
            pass

        try:
            with open(video, "rb") as video_file:

                await update.message.reply_video(
                    video=video_file,
                    supports_streaming=True,
                    caption="🤖 @UmarDownloadBot"
                )

        except Exception as error:

            print("TELEGRAM ERROR:", error)

            try:
                with open(video, "rb") as video_file:

                    await update.message.reply_document(
                        document=video_file,
                        caption="🤖 @UmarDownloadBot"
                    )

            except Exception:
                await update.message.reply_text(
                    "❌ Videoni yuborishda xatolik yuz berdi."
                )


class HealthHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"UmarDownloadBot is running"
        )

    def log_message(self, format, *args):
        pass


def run_web_server():

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    server = http.server.ThreadingHTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print("Web server running on port", port)

    server.serve_forever()


def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN topilmadi"
        )

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    app = Application.builder().token(
        BOT_TOKEN
    ).build()

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("UmarDownloadBot ishga tushdi")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
