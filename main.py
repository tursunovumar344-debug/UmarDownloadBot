import os
import re
import json
import asyncio
import tempfile
import threading
import http.server
from pathlib import Path

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


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

DATA_FILE = Path("users.json")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

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
    url_lower = url.lower()

    return any(
        domain in url_lower
        for domain in ALLOWED_DOMAINS
    )


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
            json.dump(
                users,
                file,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as error:
        print("USERS SAVE ERROR:", error)


def register_user(update):
    if not update.effective_user:
        return

    user_id = str(update.effective_user.id)

    users = load_users()

    if user_id not in users:
        users[user_id] = {
            "name": update.effective_user.first_name or ""
        }

        save_users(users)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update)

    await update.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "📥 Instagram, TikTok yoki YouTube "
        "havolasini yuboring.\n\n"
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
        "📊 Bot statistikasi\n\n"
        f"👤 Jami foydalanuvchilar: {len(users)}"
    )


def download_video_sync(url, folder):
    output = str(
        Path(folder) / "source.%(ext)s"
    )

    options = {
        "outtmpl": output,

        "format": (
            "bestvideo+bestaudio/"
            "best"
        ),

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

    files = list(
        Path(folder).glob("source.*")
    )

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
        reverse=True,
    )

    return files[0]


def convert_to_telegram_mp4(input_file, output_file):
    command = [
        FFMPEG,
        "-y",
        "-i",
        str(input_file),

        "-vf",
        "scale='min(720,iw)':'-2'",

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "27",

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-movflags",
        "+faststart",

        str(output_file),
    ]

    try:
        result = asyncio.run(
            asyncio.to_thread(
                _run_ffmpeg,
                command,
            )
        )

        if result != 0:
            return False

    except Exception as error:
        print("CONVERT ERROR:", error)
        return False

    return (
        Path(output_file).exists()
        and Path(output_file).stat().st_size > 0
    )


def _run_ffmpeg(command):
    import subprocess

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print(
            "FFMPEG ERROR:",
            result.stderr[-3000:],
        )

    return result.returncode


async def prepare_video(input_file, output_file):
    return await asyncio.to_thread(
        _convert_sync,
        input_file,
        output_file,
    )


def _convert_sync(input_file, output_file):
    import subprocess

    command = [
        FFMPEG,
        "-y",
        "-i",
        str(input_file),

        "-vf",
        "scale='min(720,iw)':'-2'",

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "27",

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-movflags",
        "+faststart",

        str(output_file),
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print(
            "FFMPEG ERROR:",
            result.stderr[-3000:],
        )
        return False

    return (
        Path(output_file).exists()
        and Path(output_file).stat().st_size > 0
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not update.message.text:
        return

    register_user(update)

    url = get_url(
        update.message.text.strip()
    )

    if not url:
        return

    if not is_supported(url):
        await update.message.reply_text(
            "❌ Bu havola qo‘llab-quvvatlanmaydi.\n\n"
            "Instagram, TikTok yoki YouTube "
            "havolasini yuboring."
        )
        return

    loading = await update.message.reply_text(
        "⏳ Yuklanmoqda..."
    )

    folder = tempfile.mkdtemp()

    try:
        source = await asyncio.to_thread(
            download_video_sync,
            url,
            folder,
        )

        if source is None:
            await loading.edit_text(
                "❌ Videoni yuklab bo‘lmadi."
            )
            return

        final_video = (
            Path(folder) / "telegram_video.mp4"
        )

        success = await prepare_video(
            source,
            final_video,
        )

        if not success:
            await loading.edit_text(
                "❌ Videoni tayyorlashda xatolik."
            )
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
                        callback_data="round_video",
                    )
                ]
            ]
        )

        with open(
            final_video,
            "rb"
        ) as video_file:

            await update.message.reply_video(
                video=video_file,
                supports_streaming=True,
                caption="🤖 @UmarDownloadBot",
                reply_markup=keyboard,
            )

    except Exception as error:
        print(
            "HANDLE ERROR:",
            error,
        )

        try:
            await loading.edit_text(
                "❌ Videoni yuborishda xatolik yuz berdi."
            )
        except Exception:
            pass

    finally:
        try:
            for file in Path(folder).iterdir():
                file.unlink()

            Path(folder).rmdir()

        except Exception:
            pass


def make_round_video_sync(
    input_file,
    output_file,
):
    import subprocess

    command = [
        FFMPEG,
        "-y",
        "-i",
        str(input_file),

        "-t",
        "60",

        "-vf",
        (
            "crop="
            "min(iw\\,ih):"
            "min(iw\\,ih):"
            "(iw-min(iw\\,ih))/2:"
            "(ih-min(iw\\,ih))/2,"
            "scale=480:480"
        ),

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "28",

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "aac",

        "-b:a",
        "96k",

        "-movflags",
        "+faststart",

        str(output_file),
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print(
            "ROUND FFMPEG ERROR:",
            result.stderr[-3000:],
        )
        return False

    return (
        Path(output_file).exists()
        and Path(output_file).stat().st_size > 0
    )


async def round_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    message = query.message

    if not message:
        return

    status = await message.reply_text(
        "🔄 Dumaloq video tayyorlanmoqda..."
    )

    folder = tempfile.mkdtemp()

    try:
        if not message.video:
            await status.edit_text(
                "❌ Asl video topilmadi."
            )
            return

        input_file = (
            Path(folder) / "input.mp4"
        )

        output_file = (
            Path(folder) / "round.mp4"
        )

        telegram_file = await context.bot.get_file(
            message.video.file_id
        )

        await telegram_file.download_to_drive(
            custom_path=str(input_file)
        )

        success = await asyncio.to_thread(
            make_round_video_sync,
            input_file,
            output_file,
        )

        if not success:
            await status.edit_text(
                "❌ Dumaloq video yaratib bo‘lmadi."
            )
            return

        try:
            await status.delete()
        except Exception:
            pass

        with open(
            output_file,
            "rb"
        ) as video_file:

            await message.reply_video_note(
                video_note=video_file
            )

    except Exception as error:
        print(
            "ROUND VIDEO ERROR:",
            error,
        )

        try:
            await status.edit_text(
                "❌ Dumaloq video yaratishda xatolik."
            )
        except Exception:
            pass

    finally:
        try:
            for file in Path(folder).iterdir():
                file.unlink()

            Path(folder).rmdir()

        except Exception:
            pass


class HealthHandler(
    http.server.BaseHTTPRequestHandler
):
    def do_GET(self):
        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain",
        )

        self.end_headers()

        self.wfile.write(
            b"UmarDownloadBot is running"
        )

    def log_message(
        self,
        format,
        *args,
    ):
        pass


def run_web_server():
    port = int(
        os.environ.get(
            "PORT",
            "10000",
        )
    )

    server = http.server.ThreadingHTTPServer(
        ("0.0.0.0", port),
        HealthHandler,
    )

    print(
        "Web server running on port",
        port,
    )

    server.serve_forever()


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN topilmadi"
        )

    threading.Thread(
        target=run_web_server,
        daemon=True,
    ).start()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            round_video,
            pattern="^round_video$",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
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
