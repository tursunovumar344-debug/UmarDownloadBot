import os
import re
import json
import time
import uuid
import shutil
import tempfile
import threading
import subprocess
import asyncio

from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

import yt_dlp
import imageio_ffmpeg

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# ==========================================
# SOZLAMALAR
# ==========================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

USERS_FILE = "users.json"

ALLOWED_DOMAINS = (
    "instagram.com",
    "www.instagram.com",
    "tiktok.com",
    "www.tiktok.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
)

# Dumaloq video uchun vaqtincha saqlanadigan videolar
VIDEO_CACHE = {}

CACHE_TIME = 30 * 60


# ==========================================
# USERLAR
# ==========================================

def load_users():
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as file:
                return set(json.load(file))
    except Exception as error:
        print("USERS LOAD ERROR:", error)

    return set()


def save_users(users):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as file:
            json.dump(list(users), file)
    except Exception as error:
        print("USERS SAVE ERROR:", error)


def register_user(user_id):
    users = load_users()

    if user_id not in users:
        users.add(user_id)
        save_users(users)


# ==========================================
# LINK TEKSHIRISH
# ==========================================

def is_supported_url(text):
    if not text:
        return False

    text = text.strip()

    if not re.match(r"^https?://", text, re.IGNORECASE):
        return False

    try:
        domain = text.split("/")[2].lower().split(":")[0]

        return domain in ALLOWED_DOMAINS

    except Exception:
        return False


# ==========================================
# ESKI VIDEOLARNI TOZALASH
# ==========================================

def cleanup_cache():
    now = time.time()

    for video_id, data in list(VIDEO_CACHE.items()):
        try:
            if now - data["time"] > CACHE_TIME:

                folder = data.get("folder")

                if folder and os.path.exists(folder):
                    shutil.rmtree(folder, ignore_errors=True)

                del VIDEO_CACHE[video_id]

        except Exception as error:
            print("CACHE CLEAN ERROR:", error)


def cleanup_loop():
    while True:
        cleanup_cache()
        time.sleep(300)


# ==========================================
# START
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    register_user(update.effective_user.id)

    text = (
        "👋 Assalomu alaykum!\n\n"
        "📥 Instagram, TikTok yoki YouTube linkini yuboring.\n\n"
        "⚡ Video avtomatik yuklanadi.\n"
        "🔵 Video ostidagi «Dumaloq video» tugmasini "
        "bosib dumaloq video olishingiz mumkin.\n\n"
        "🤖 @UmarDownloadBot"
    )

    await update.message.reply_text(text)


# ==========================================
# STATISTIKA
# ==========================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if ADMIN_ID == 0:
        return

    if update.effective_user.id != ADMIN_ID:
        return

    users = load_users()

    await update.message.reply_text(
        f"📊 Bot statistikasi\n\n"
        f"👤 Foydalanuvchilar: {len(users)}"
    )


# ==========================================
# VIDEO YUKLASH
# ==========================================

def download_video(url, folder):

    output_template = os.path.join(
        folder,
        "%(id)s.%(ext)s"
    )

    ydl_opts = {
        # Avval tayyor MP4 olishga harakat qiladi.
        # Bu oddiy videoni tezroq yuborishga yordam beradi.
        "format": (
            "best[ext=mp4][vcodec^=avc1]/"
            "best[ext=mp4]/"
            "bestvideo[vcodec^=avc1]+bestaudio/"
            "bestvideo[ext=mp4]+bestaudio/"
            "best"
        ),

        "outtmpl": output_template,

        "quiet": True,
        "no_warnings": True,

        "noplaylist": True,

        # imageio-ffmpeg ichidagi FFmpeg
        "ffmpeg_location": FFMPEG,

        "merge_output_format": "mp4",

        # Tezroq yuklash
        "concurrent_fragment_downloads": 4,

        "retries": 3,
        "fragment_retries": 3,

        "socket_timeout": 30,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )

        downloaded = ydl.prepare_filename(info)

        # MP4 tekshirish
        mp4_file = (
            os.path.splitext(downloaded)[0]
            + ".mp4"
        )

        if os.path.exists(mp4_file):
            return mp4_file

        if os.path.exists(downloaded):
            return downloaded

        # Papkadagi eng katta fayl
        files = []

        for file in Path(folder).iterdir():

            if file.is_file():
                files.append(file)

        if not files:
            raise Exception("Video topilmadi")

        files.sort(
            key=lambda x: x.stat().st_size,
            reverse=True
        )

        return str(files[0])


# ==========================================
# LINK QABUL QILISH
# ==========================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    register_user(update.effective_user.id)

    url = update.message.text.strip()

    if not is_supported_url(url):

        await update.message.reply_text(
            "❌ Instagram, TikTok yoki YouTube link yuboring."
        )

        return

    status_message = await update.message.reply_text(
        "⏳ Yuklanmoqda..."
    )

    folder = tempfile.mkdtemp(
        prefix="umarbot_"
    )

    try:

        # Yuklashni alohida thread'da bajarish
        video_file = await asyncio.to_thread(
            download_video,
            url,
            folder
        )

        if not os.path.exists(video_file):
            raise Exception(
                "Video fayli topilmadi"
            )

        # Dumaloq video keyin kerak bo'lishi uchun
        # original videoni vaqtincha saqlaymiz.
        video_id = uuid.uuid4().hex[:16]

        VIDEO_CACHE[video_id] = {
            "file": video_file,
            "folder": folder,
            "time": time.time(),
        }

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔵 Dumaloq video",
                    callback_data=f"round:{video_id}"
                )
            ]
        ])

        # Oddiy video darhol yuboriladi
        with open(video_file, "rb") as video:

            await update.message.reply_video(
                video=video,
                caption="🤖 @UmarDownloadBot",
                supports_streaming=True,
                reply_markup=keyboard,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
                write_timeout=120,
            )

        # Yuklanmoqda xabarini o'chirish
        try:
            await status_message.delete()
        except Exception:
            pass

    except Exception as error:

        print(
            "DOWNLOAD ERROR:",
            repr(error)
        )

        try:

            await status_message.edit_text(
                "❌ Videoni yuklab bo‘lmadi.\n"
                "Linkni tekshirib qayta yuboring."
            )

        except Exception:
            pass

        shutil.rmtree(
            folder,
            ignore_errors=True
        )


# ==========================================
# DUMALOQ VIDEO TAYYORLASH
# ==========================================

def make_round_video(
    source_file,
    output_file
):

    command = [
        FFMPEG,

        "-y",

        "-i",
        source_file,

        # Video note uchun kvadrat format
        # Asl video cho'zilmaydi.
        "-vf",
        (
            "scale=640:640:"
            "force_original_aspect_ratio=decrease,"
            "pad=640:640:(ow-iw)/2:(oh-ih)/2"
        ),

        "-c:v",
        "libx264",

        # Tez encoding
        "-preset",
        "veryfast",

        "-crf",
        "28",

        "-pix_fmt",
        "yuv420p",

        # Video note'da audio kerak emas
        "-an",

        # Telegram video note maksimal 60 sekund
        "-t",
        "60",

        "-movflags",
        "+faststart",

        output_file,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )

    if result.returncode != 0:

        error = result.stderr.decode(
            "utf-8",
            errors="ignore"
        )

        print(
            "FFMPEG ERROR:",
            error[-3000:]
        )

        raise Exception(
            "Dumaloq video tayyorlanmadi"
        )


# ==========================================
# DUMALOQ TUGMA
# ==========================================

async def round_video_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer(
        "🔄 Tayyorlanmoqda..."
    )

    data = query.data

    if not data.startswith("round:"):
        return

    video_id = data.split(
        ":",
        1
    )[1]

    video_data = VIDEO_CACHE.get(
        video_id
    )

    if not video_data:

        await query.message.reply_text(
            "❌ Bu video uchun vaqt tugagan.\n"
            "Linkni qaytadan yuboring."
        )

        return

    source_file = video_data["file"]

    folder = video_data["folder"]

    if not os.path.exists(source_file):

        await query.message.reply_text(
            "❌ Asl video topilmadi.\n"
            "Linkni qaytadan yuboring."
        )

        return

    round_file = os.path.join(
        folder,
        "round_video.mp4"
    )

    try:

        await query.message.reply_text(
            "🔄 Dumaloq video tayyorlanmoqda..."
        )

        # Faqat tugma bosilganda ishlaydi
        await asyncio.to_thread(
            make_round_video,
            source_file,
            round_file
        )

        if not os.path.exists(round_file):
            raise Exception(
                "Dumaloq fayl yaratilmadi"
            )

        # Telegram dumaloq video
        with open(
            round_file,
            "rb"
        ) as video:

            await query.message.reply_video_note(
                video_note=video,
                length=640,
                duration=60,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
            )

    except Exception as error:

        print(
            "ROUND ERROR:",
            repr(error)
        )

        await query.message.reply_text(
            "❌ Dumaloq video tayyorlashda "
            "xatolik yuz berdi."
        )


# ==========================================
# ERROR
# ==========================================

async def error_handler(
    update,
    context
):

    print(
        "BOT ERROR:",
        repr(context.error)
    )


# ==========================================
# RENDER PORT
# ==========================================

class HealthHandler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()

        self.wfile.write(
            b"UmarDownloadBot is running"
        )

    def log_message(
        self,
        format,
        *args
    ):
        return


def start_server():

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    server = HTTPServer(
        (
            "0.0.0.0",
            port
        ),
        HealthHandler
    )

    print(
        f"HTTP server running on port {port}"
    )

    server.serve_forever()


# ==========================================
# MAIN
# ==========================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN topilmadi!"
        )

    # Render uchun port
    threading.Thread(
        target=start_server,
        daemon=True
    ).start()

    # Eski videolarni tozalash
    threading.Thread(
        target=cleanup_loop,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            round_video_callback,
            pattern=r"^round:"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    application.add_error_handler(
        error_handler
    )

    print(
        "UmarDownloadBot ishga tushdi!"
    )

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
