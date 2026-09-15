import os
import re
import json
import asyncio
import tempfile
import threading
import http.server
from pathlib import Path

import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

DATA_FILE = Path("users.json")

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


def load_users():
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)

                if isinstance(data, dict):
                    return data

    except Exception as error:
        print("USERS LOAD ERROR:", error)

    return {}


def save_users(users):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(users, file, ensure_ascii=False, indent=2)

    except Exception as error:
        print("USERS SAVE ERROR:", error)


def register_user(update):
    if not update.effective_user:
        return

    user_id = str(update.effective_user.id)

    users = load_users()

    if user_id not in users:
        users[user_id] = {
            "first_seen": str(asyncio.get_event_loop().time())
        }

        save_users(users)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update)

    await update.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "Instagram, TikTok yoki YouTube havolasini yuboring.\n\n"
        "🤖 @UmarDownloadBot"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return

    if not ADMIN_ID:
        await update.message.reply_text(
            "❌ ADMIN_ID sozlanmagan."
        )
        return

    if str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text(
            "❌ Bu buyruq faqat bot egasi uchun."
        )
        return

    users = load_users()

    await update.message.reply_text(
        f"📊 Bot statistikasi\n\n"
        f"👤 Jami foydalanuvchilar: {len(users)}"
    )


def download_video_sync(url, folder):
    output = str(Path(folder) / "video.%(ext)s")

    options = {
        "outtmpl": output,
        "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "merge_output_format": "mp4",
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

    except Exception as error:
        print("DOWNLOAD ERROR:", error)
        return None

    files = list(Path(folder).glob("video.*"))

    files = [
        file
        for file in files
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

    register_user(update)

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

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔘 Dumaloq video",
                        callback_data="round_video"
                    )
                ]
            ]
        )

        try:
            with open(video, "rb") as video_file:

                await update.message.reply_video(
                    video=video_file,
                    supports_streaming=True,
                    caption="🤖 @UmarDownloadBot",
                    reply_markup=keyboard
                )

        except Exception as error:

            print("TELEGRAM VIDEO ERROR:", error)

            try:
                with open(video, "rb") as video_file:

                    await update.message.reply_document(
                        document=video_file,
                        caption="🤖 @UmarDownloadBot",
                        reply_markup=keyboard
                    )

            except Exception as document_error:

                print("TELEGRAM DOCUMENT ERROR:", document_error)

                await update.message.reply_text(
                    "❌ Videoni yuborishda xatolik yuz berdi."
                )


async def round_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    message = query.message

    if not message:
        return

    await query.edit_message_reply_markup(
        reply_markup=None
    )

    await message.reply_text(
        "🔄 Dumaloq video tayyorlanmoqda..."
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

    print(
        "Web server running on port",
        port
    )

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
        CommandHandler(
            "stats",
            stats
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            round_video,
            pattern="^round_video$"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        "UmarDownloadBot ishga tushdi"
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
