import os
import logging
import requests
import asyncio
import re
import time
import json
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackContext 

# --- CONFIGURATION (from environment variables) ---
YOUR_TELEGRAM_BOT_TOKEN = os.getenv("YOUR_TELEGRAM_BOT_TOKEN")
YOUR_API_BASE_URL = os.getenv("YOUR_API_BASE_URL", "https://socialdown.itz-ashlynn.workers.dev") 
COMMAND_COOLDOWN = 7  # 7 seconds
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
# --- END CONFIGURATION ---

# Safety checks
if not YOUR_TELEGRAM_BOT_TOKEN:
    raise ValueError("YOUR_TELEGRAM_BOT_TOKEN environment variable is required!")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS environment variable is required!")

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Statistics tracking
stats = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "users": set(),
    "commands_used": {},
    "start_time": datetime.now()
}

def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return user_id in ADMIN_IDS

async def call_api(endpoint: str, url: str, **kwargs) -> dict:
    """
    Calls the social downloader API asynchronously and returns the JSON response.
    """
    try:
        full_url = f"{YOUR_API_BASE_URL}/{endpoint}"
        params = {'url': url}
        params.update(kwargs)
        
        response = await asyncio.to_thread(
            requests.get, full_url, params=params, timeout=20
        )
        
        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error for {endpoint} ({url}): {e}")
        try:
            return e.response.json()
        except:
            return {"success": False, "error": f"HTTP Error: {e.response.status_code}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"Request Error for {endpoint} ({url}): {e}")
        return {"success": False, "error": f"Request failed: {str(e)}"}

async def loading_animation(msg):
    """Show loading animation."""
    spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    i = 0
    try:
        while True:
            await msg.edit_text(f"{spinner[i]} Processing...")
            i = (i + 1) % len(spinner)
            await asyncio.sleep(0.3)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

def check_cooldown(context: CallbackContext, user_id: int) -> (bool, float):
    """Check if user is on cooldown (admins bypass cooldown)."""
    if is_admin(user_id):
        return False, 0
    
    current_time = time.time()
    user_data = context.user_data
    last_called = user_data.get('last_command_time', 0)
    
    if current_time - last_called < COMMAND_COOLDOWN:
        wait_time = round(COMMAND_COOLDOWN - (current_time - last_called), 1)
        return True, wait_time
    
    user_data['last_command_time'] = current_time
    return False, 0

def track_command(user_id: int, command: str, success: bool):
    """Track command usage statistics."""
    stats["total_requests"] += 1
    stats["users"].add(user_id)
    
    if success:
        stats["successful_requests"] += 1
    else:
        stats["failed_requests"] += 1
    
    if command not in stats["commands_used"]:
        stats["commands_used"][command] = 0
    stats["commands_used"][command] += 1

async def send_media_from_url(update: Update, file_url: str, media_type: str, caption: str, filename_prefix: str = "download") -> bool:
    """Download and send media file."""
    try:
        r = await asyncio.to_thread(requests.get, file_url, timeout=60, allow_redirects=True)
        r.raise_for_status()
        media_bytes = r.content

        filename = f"{filename_prefix}.{media_type if media_type != 'photo' else 'jpg'}"
        if "content-disposition" in r.headers:
            match = re.search(r'filename="?([^"]+)"?', r.headers["content-disposition"])
            if match:
                filename = match.group(1)
        
        if media_type == 'video':
            if len(media_bytes) > 50 * 1024 * 1024:
                raise ValueError("File is > 50MB")
            await update.message.reply_video(video=media_bytes, caption=caption, filename=filename, parse_mode=ParseMode.HTML)
        elif media_type == 'audio':
            if len(media_bytes) > 50 * 1024 * 1024:
                raise ValueError("File is > 50MB")
            await update.message.reply_audio(audio=media_bytes, caption=caption, filename=filename, parse_mode=ParseMode.HTML)
        elif media_type == 'photo':
            if len(media_bytes) > 10 * 1024 * 1024:
                raise ValueError("File is > 10MB")
            await update.message.reply_photo(photo=media_bytes, caption=caption, filename=filename, parse_mode=ParseMode.HTML)
        
        return True
    except Exception as e:
        logger.warning(f"Failed to send_media_from_url ({file_url}): {e}")
        return False

# --- BOT COMMAND HANDLERS ---

async def start(update: Update, context: CallbackContext) -> None:
    """Send welcome message."""
    user = update.effective_user
    message = f"""
👋 <b>Welcome {user.first_name}!</b>

I'm your <b>Social Media Downloader Bot</b> - Download content from various platforms instantly!

<b>📱 Supported Platforms:</b>

<b>🎥 Video & Media</b>
• /instagram - Instagram posts (video/photo)
• /facebook - Facebook videos
• /tiktok - TikTok videos
• /x - X (Twitter) media
• /pinterest - Pinterest content
• /youtube - YouTube videos
• /threads - Threads posts

<b>🎵 Audio</b>
• /spotify - Spotify tracks
• /soundcloud - SoundCloud tracks

<b>🛠️ Utilities</b>
• /mediafire - MediaFire files
• /capcut - CapCut templates
• /yt_trans - YouTube transcripts

<b>💡 Example:</b>
<code>/tiktok https://www.tiktok.com/@...</code>

<b>ℹ️ Info Commands:</b>
• /help - Show this message
• /about - About this bot

━━━━━━━━━━━━━━━━━
"""
    await update.message.reply_html(message, disable_web_page_preview=True)

async def help_command(update: Update, context: CallbackContext) -> None:
    """Show help message."""
    await start(update, context)

async def about(update: Update, context: CallbackContext) -> None:
    """Show about information."""
    uptime = datetime.now() - stats["start_time"]
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    message = f"""
<b>📊 About This Bot</b>

<b>🤖 Bot Name:</b> Social Downloader Bot
<b>⏱️ Uptime:</b> {days}d {hours}h {minutes}m

<b>✨ Features:</b>
• Download from 10+ platforms
• High-quality downloads
• Fast processing
• User-friendly interface

<b>📈 Statistics:</b>
• Total Users: {len(stats['users'])}
• Total Requests: {stats['total_requests']}
• Success Rate: {(stats['successful_requests']/stats['total_requests']*100) if stats['total_requests'] > 0 else 0:.1f}%

<b>🆘 Support:</b> Use /help for commands

<i>Thank you for using this bot!</i>
"""
    await update.message.reply_html(message)

# --- ADMIN COMMANDS ---

async def stats_command(update: Update, context: CallbackContext) -> None:
    """Show detailed statistics (Admin only)."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return
    
    uptime = datetime.now() - stats["start_time"]
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # Top 5 most used commands
    top_commands = sorted(stats["commands_used"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_commands_str = "\n".join([f"  • /{cmd}: {count}" for cmd, count in top_commands])
    
    message = f"""
<b>📊 Bot Statistics (Admin)</b>

<b>⏱️ Uptime:</b> {days}d {hours}h {minutes}m {seconds}s
<b>🕐 Started:</b> {stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}

<b>👥 Users:</b>
• Total Unique Users: {len(stats['users'])}

<b>📈 Requests:</b>
• Total: {stats['total_requests']}
• Successful: {stats['successful_requests']} ({(stats['successful_requests']/stats['total_requests']*100) if stats['total_requests'] > 0 else 0:.1f}%)
• Failed: {stats['failed_requests']} ({(stats['failed_requests']/stats['total_requests']*100) if stats['total_requests'] > 0 else 0:.1f}%)

<b>🔥 Top Commands:</b>
{top_commands_str if top_commands else "  No commands used yet"}

<b>⚙️ System:</b>
• API Base: {YOUR_API_BASE_URL}
• Cooldown: {COMMAND_COOLDOWN}s
"""
    await update.message.reply_html(message)

async def broadcast(update: Update, context: CallbackContext) -> None:
    """Broadcast message to all users (Admin only)."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: <b>/broadcast &lt;message&gt;</b>\n\n"
            "This will send the message to all users who have used the bot.",
            parse_mode=ParseMode.HTML
        )
        return
    
    broadcast_msg = " ".join(context.args)
    sent = 0
    failed = 0
    
    status_msg = await update.message.reply_text(f"📢 Broadcasting to {len(stats['users'])} users...")
    
    for uid in stats['users']:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 <b>Broadcast Message</b>\n\n{broadcast_msg}",
                parse_mode=ParseMode.HTML
            )
            sent += 1
            await asyncio.sleep(0.05)  # Avoid rate limits
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to send broadcast to {uid}: {e}")
    
    await status_msg.edit_text(
        f"✅ Broadcast complete!\n\n"
        f"• Sent: {sent}\n"
        f"• Failed: {failed}\n"
        f"• Total: {len(stats['users'])}"
    )

async def adminhelp(update: Update, context: CallbackContext) -> None:
    """Show admin commands (Admin only)."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return
    
    message = """
<b>🔐 Admin Commands</b>

<b>/stats</b> - View detailed bot statistics
<b>/broadcast &lt;message&gt;</b> - Send message to all users
<b>/adminhelp</b> - Show this message

<i>Note: Admins bypass cooldown restrictions.</i>
"""
    await update.message.reply_html(message)

# --- PLATFORM HANDLERS ---

async def handle_instagram(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return

    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/instagram &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    
    try:
        data = await call_api("insta", url=context.args[0]) 
        
        if data and data.get("success"):
            links = data.get("urls", [])
            if not links:
                await msg.edit_text("API success, but no URLs were found.")
                track_command(user_id, "instagram", False)
                return

            fallback_links = []
            uploaded_count = 0
            
            for i, file_url in enumerate(links, 1):
                await msg.edit_text(f"⏬ Downloading {i}/{len(links)}...")
                success = await send_media_from_url(update, file_url, 'video', f"📸 Instagram Media {i}/{len(links)}", f"instagram_{i}")
                
                if success:
                    uploaded_count += 1
                else:
                    fallback_links.append(file_url)
            
            await msg.delete()

            if fallback_links:
                end_time = time.time()
                duration = round(end_time - start_time, 2)
                reply = f"✅ {uploaded_count} files uploaded. The following were too large:\n\n"
                for i, link in enumerate(fallback_links, 1):
                    reply += f"🔗 <a href='{link}'>Download Link {i}</a>\n"
                reply += f"\n<i>⏱️ {duration}s</i>"
                await update.message.reply_html(reply, disable_web_page_preview=True)
            
            track_command(user_id, "instagram", True)
        else:
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            error = data.get("error", "Unknown error")
            await msg.edit_text(f"❌ <b>Error:</b> {error}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)
            track_command(user_id, "instagram", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_instagram: {e}")
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        await msg.edit_text(f"❌ An unexpected error occurred.\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)
        track_command(user_id, "instagram", False)
    finally:
        loading_task.cancel()

async def handle_facebook(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return

    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/facebook &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    final_reply = ""
    msg_deleted = False

    try:
        data = await call_api("fb", url=context.args[0])
        
        if data and data.get("success"):
            hd_url = data.get("hd")
            sd_url = data.get("sd")
            audio_url = data.get("audio")
            sent = False
            
            if hd_url:
                await msg.edit_text("⏬ Downloading HD video...")
                sent = await send_media_from_url(update, hd_url, 'video', "🎥 Facebook Video (HD)", "facebook_hd")
            
            if not sent and sd_url:
                await msg.edit_text("⏬ Downloading SD video...")
                sent = await send_media_from_url(update, sd_url, 'video', "🎥 Facebook Video (SD)", "facebook_sd")

            if not sent and audio_url:
                 await msg.edit_text("⏬ Downloading audio...")
                 sent = await send_media_from_url(update, audio_url, 'audio', "🎵 Facebook Audio", "facebook_audio")

            if sent:
                await msg.delete()
                msg_deleted = True
                track_command(user_id, "facebook", True)
            else:
                final_reply = "⚠️ Could not auto-send media. Here are the links:\n"
                if hd_url: final_reply += f"🎥 <a href='{hd_url}'>HD Video</a>\n"
                if sd_url: final_reply += f"📹 <a href='{sd_url}'>SD Video</a>\n"
                if audio_url: final_reply += f"🎵 <a href='{audio_url}'>Audio Only</a>\n"
                if not (hd_url or sd_url or audio_url):
                    final_reply = "API success, but no media links found."
                track_command(user_id, "facebook", False)
        else:
            error = data.get("error", "Unknown error")
            final_reply = f"❌ <b>Error:</b> {error}"
            track_command(user_id, "facebook", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_facebook: {e}")
        final_reply = "❌ An unexpected error occurred."
        track_command(user_id, "facebook", False)
    finally:
        loading_task.cancel()
        if not msg_deleted:
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            await msg.edit_text(f"{final_reply}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def handle_spotify(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return
        
    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/spotify &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return
        
    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    final_reply = ""
    msg_deleted = False

    try:
        data = await call_api("spotify", url=context.args[0])
        
        if data and data.get("success"):
            dl_url = data.get("download_url")
            caption = f"""
🎵 <b>{data.get('name', 'N/A')}</b>
🎤 <i>{', '.join(data.get('artists', []))}</i>
"""
            if dl_url:
                await msg.edit_text("⏬ Downloading audio...")
                if data.get("image"):
                    await update.message.reply_photo(photo=data.get("image"))
                
                success = await send_media_from_url(update, dl_url, 'audio', caption, data.get('name', 'song'))
                if success:
                    await msg.delete()
                    msg_deleted = True
                    track_command(user_id, "spotify", True)
                else:
                    final_reply = f"⚠️ Audio was too large. Here is the link:\n{caption}\n🔗 <a href='{dl_url}'>Download Track</a>"
                    track_command(user_id, "spotify", False)
            else:
                final_reply = f"API success, but no download URL found.\n{caption}"
                track_command(user_id, "spotify", False)
        else:
            error = data.get("error", "Unknown error")
            final_reply = f"❌ <b>Error:</b> {error}"
            track_command(user_id, "spotify", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_spotify: {e}")
        final_reply = "❌ An unexpected error occurred."
        track_command(user_id, "spotify", False)
    finally:
        loading_task.cancel()
        if not msg_deleted:
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            await msg.edit_text(f"{final_reply}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def handle_mediafire(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return

    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/mediafire &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    final_reply = ""
    
    try:
        data = await call_api("mediafire", url=context.args[0])
        
        if data and data.get("success"):
            final_reply = f"""
✅ <b>MediaFire File Found!</b>

📄 <b>Name:</b> <code>{data.get('name', 'N/A')}</code>
💾 <b>Size:</b> <code>{data.get('size', 'N/A')} bytes</code>
🔗 <a href='{data.get('download')}'>Download Link</a>
"""
            track_command(user_id, "mediafire", True)
        else:
            error = data.get("error", "Unknown error")
            final_reply = f"❌ <b>Error:</b> {error}"
            track_command(user_id, "mediafire", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_mediafire: {e}")
        final_reply = "❌ An unexpected error occurred."
        track_command(user_id, "mediafire", False)
    finally:
        loading_task.cancel()
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        await msg.edit_text(f"{final_reply}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def handle_x(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return
        
    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/x &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return
        
    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    
    try:
        data = await call_api("x", url=context.args[0])
        
        if data and data.get("success") and data.get("found"):
            media_list = data.get("media", [])
            if not media_list:
                await msg.edit_text("Post found, but no media links were returned.")
                track_command(user_id, "x", False)
                return

            caption = f"✅ Media from <b>{data.get('authorName', 'N/A')}</b> (<code>@{data.get('authorUsername', 'N/A')}</code>)"
            fallback_links = []
            uploaded_count = 0

            for i, item in enumerate(media_list, 1):
                file_url = item.get("url")
                media_type = 'video' if item.get("type") == 'video' else 'photo'
                
                await msg.edit_text(f"⏬ Downloading {i}/{len(media_list)}...")
                success = await send_media_from_url(update, file_url, media_type, caption if i == 1 else "", f"x_{i}")
                
                if success:
                    uploaded_count += 1
                else:
                    fallback_links.append(file_url)
            
            await msg.delete()

            if fallback_links:
                end_time = time.time()
                duration = round(end_time - start_time, 2)
                reply = f"✅ {uploaded_count} files uploaded. The following were too large:\n{caption}\n"
                for i, link in enumerate(fallback_links, 1):
                    reply += f"🔗 <a href='{link}'>Download Link {i}</a>\n"
                reply += f"\n<i>⏱️ {duration}s</i>"
                await update.message.reply_html(reply, disable_web_page_preview=True)
            
            track_command(user_id, "x", True)
        else:
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            error = data.get("error", "Unknown error or post not found")
            await msg.edit_text(f"❌ <b>Error:</b> {error}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)
            track_command(user_id, "x", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_x: {e}")
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        await msg.edit_text(f"❌ An unexpected error occurred.\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)
        track_command(user_id, "x", False)
    finally:
        loading_task.cancel()

async def handle_tiktok(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return
        
    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/tiktok &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return
        
    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    final_reply = ""
    msg_deleted = False

    try:
        data = await call_api("tiktok", url=context.args[0])
        
        if data and data.get("success"):
            video_data = data.get("data", [])
            if video_data and isinstance(video_data, list) and video_data[0].get("downloadLinks"):
                video = video_data[0]
                dl_url = video["downloadLinks"][0].get("link")
                
                caption = f"🎬 <b>{video.get('title', 'TikTok Video')}</b>"

                if dl_url:
                    await msg.edit_text("⏬ Downloading video...")
                    if video.get("thumbnail"):
                         await update.message.reply_photo(photo=video.get("thumbnail"))

                    success = await send_media_from_url(update, dl_url, 'video', caption, video.get('title', 'tiktok'))
                    if success:
                        await msg.delete()
                        msg_deleted = True
                        track_command(user_id, "tiktok", True)
                    else:
                        final_reply = f"⚠️ Video was too large. Here are the links:\n{caption}\n"
                        for link_info in video.get("downloadLinks", []):
                            final_reply += f"🔗 <a href='{link_info.get('link')}'>{link_info.get('text')}</a>\n"
                        track_command(user_id, "tiktok", False)
                else:
                    final_reply = "API success, but no download links found."
                    track_command(user_id, "tiktok", False)
            else:
                final_reply = "API success, but no video data was found."
                track_command(user_id, "tiktok", False)
        else:
            error = data.get("error", "Unknown error")
            final_reply = f"❌ <b>Error:</b> {error}"
            track_command(user_id, "tiktok", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_tiktok: {e}")
        final_reply = "❌ An unexpected error occurred."
        track_command(user_id, "tiktok", False)
    finally:
        loading_task.cancel()
        if not msg_deleted:
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            await msg.edit_text(f"{final_reply}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def handle_capcut(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return
        
    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/capcut &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return
        
    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    
    try:
        data = await call_api("capcut", url=context.args[0])
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        
        if data and data.get("success"):
            reply = f"""
✨ <b>{data.get('title', 'N/A')}</b>
👤 <b>Author:</b> <code>{data.get('author', 'N/A')}</code>
❤️ <b>Likes:</b> {data.get('like', 'N/A')} | <b>Uses:</b> {data.get('usage', 'N/A')}
<i>⏱️ {duration}s</i>
"""
            await msg.delete() 
            if data.get("coverUrl"):
                await update.message.reply_photo(
                    photo=data.get("coverUrl"),
                    caption=reply,
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_html(reply, disable_web_page_preview=True)
            track_command(user_id, "capcut", True)
        else:
            error = data.get("error", "Unknown error")
            await msg.edit_text(f"❌ <b>Error:</b> {error}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)
            track_command(user_id, "capcut", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_capcut: {e}")
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        await msg.edit_text(f"❌ An unexpected error occurred.\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)
        track_command(user_id, "capcut", False)
    finally:
        loading_task.cancel()


async def handle_pinterest(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return

    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/pinterest &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    
    try:
        data = await call_api("pinterest", url=context.args[0])
        
        if data and data.get("source") == "pinterest":
            media_list = data.get("medias", [])
            if not media_list:
                await msg.edit_text("Post found, but no media links were returned.")
                track_command(user_id, "pinterest", False)
                return

            caption = f"📌 <b>{data.get('title', 'Pinterest')}</b>"
            fallback_links = []
            uploaded_count = 0

            for i, item in enumerate(media_list, 1):
                file_url = item.get("url")
                media_type = 'video' if item.get("extension") == 'mp4' else 'photo'
                
                await msg.edit_text(f"⏬ Downloading {i}/{len(media_list)}...")
                success = await send_media_from_url(update, file_url, media_type, caption if i == 1 else "", f"pinterest_{i}")
                
                if success:
                    uploaded_count += 1
                else:
                    fallback_links.append(item)
            
            await msg.delete()

            if fallback_links:
                end_time = time.time()
                duration = round(end_time - start_time, 2)
                reply = f"✅ {uploaded_count} files uploaded. The following were too large:\n{caption}\n"
                for item in fallback_links:
                    reply += f"🔗 <a href='{item.get('url')}'>{item.get('quality')} {item.get('extension')}</a> ({item.get('formattedSize')})\n"
                reply += f"\n<i>⏱️ {duration}s</i>"
                await update.message.reply_html(reply, disable_web_page_preview=True)
            
            track_command(user_id, "pinterest", True)
        else:
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            error = data.get("error", "Unknown error")
            await msg.edit_text(f"❌ <b>Error:</b> {error}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)
            track_command(user_id, "pinterest", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_pinterest: {e}")
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        await msg.edit_text(f"❌ An unexpected error occurred.\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)
        track_command(user_id, "pinterest", False)
    finally:
        loading_task.cancel()


async def handle_youtube(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return
        
    if not context.args:
        await update.message.reply_text("Usage: <b>/youtube [format] &lt;url&gt;</b>\n(Default: mp4. Use <code>/youtube mp3 &lt;url&gt;</code> for audio)", parse_mode=ParseMode.HTML)
        return
    
    video_url = ""
    video_format = "mp4"
    
    if len(context.args) == 2 and context.args[0].lower() == 'mp3':
        video_format = 'mp3'
        video_url = context.args[1]
    elif len(context.args) == 1:
        video_url = context.args[0]
    else:
        await update.message.reply_text("Invalid format. Usage: <b>/youtube [mp3] &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text(f"⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    final_reply = ""
    msg_deleted = False
    
    try:
        await msg.edit_text(f"⏳ Processing YouTube video ({video_format})...")
        data = await call_api("yt", url=video_url, format=video_format)
        
        if data and data.get("success"):
            video_data = data.get("data", [])
            if video_data and isinstance(video_data, list):
                video = video_data[0]
                dl_url = video.get("downloadUrl")
                caption = f"""
🎬 <b>{video.get('title', 'N/A')}</b>
<b>Format:</b> <code>{video.get('format', 'N/A')}</code> | <b>Size:</b> <code>{video.get('fileSize', 'N/A')}</code>
"""
                if dl_url:
                    await msg.edit_text(f"⏬ Downloading {video_format}...")
                    media_type = 'video' if video_format == 'mp4' else 'audio'
                    success = await send_media_from_url(update, dl_url, media_type, caption, video.get('title', 'youtube'))
                    if success:
                        await msg.delete()
                        msg_deleted = True
                        track_command(user_id, "youtube", True)
                    else:
                        final_reply = f"⚠️ File was too large. Here is the link:\n{caption}\n🔗 <a href='{dl_url}'>Download Link</a>"
                        track_command(user_id, "youtube", False)
                else:
                    final_reply = "API success, but no download URL found."
                    track_command(user_id, "youtube", False)
            else:
                final_reply = "API success, but no video data was found."
                track_command(user_id, "youtube", False)
        else:
            error = data.get("error", "Unknown error")
            final_reply = f"❌ <b>Error:</b> {error}"
            track_command(user_id, "youtube", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_youtube: {e}")
        final_reply = "❌ An unexpected error occurred."
        track_command(user_id, "youtube", False)
    finally:
        loading_task.cancel()
        if not msg_deleted:
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            await msg.edit_text(f"{final_reply}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def handle_soundcloud(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return

    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/soundcloud &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    final_reply = ""
    
    try:
        data = await call_api("soundcloud", url=context.args[0])
        
        if data and data.get("success"):
            final_reply = "✅ SoundCloud request successful.\n(Note: This API does not provide a download link for SoundCloud, only a success status)."
            track_command(user_id, "soundcloud", True)
        else:
            error = data.get("error", "Unknown error")
            final_reply = f"❌ <b>Error:</b> {error}"
            track_command(user_id, "soundcloud", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_soundcloud: {e}")
        final_reply = "❌ An unexpected error occurred."
        track_command(user_id, "soundcloud", False)
    finally:
        loading_task.cancel()
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        await msg.edit_text(f"{final_reply}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)


async def handle_threads(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return

    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/threads &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    final_reply = ""

    try:
        data = await call_api("threads", url=context.args[0])
        
        if data and data.get("success"):
            final_reply = "✅ Threads request successful.\n(Note: This API does not provide a download link for Threads, only a success status)."
            track_command(user_id, "threads", True)
        else:
            error = data.get("error", "Unknown error")
            final_reply = f"❌ <b>Error:</b> {error}"
            track_command(user_id, "threads", False)
            
    except Exception as e:
        logger.error(f"Unexpected error in handle_threads: {e}")
        final_reply = "❌ An unexpected error occurred."
        track_command(user_id, "threads", False)
    finally:
        loading_task.cancel()
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        await msg.edit_text(f"{final_reply}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)


async def handle_yt_trans(update: Update, context: CallbackContext) -> None:
    start_time = time.time()
    user_id = update.effective_user.id
    on_cooldown, wait_time = check_cooldown(context, user_id)
    
    if on_cooldown:
        await update.message.reply_text(f"⏳ Please wait <b>{wait_time}s</b> before using another command.", parse_mode=ParseMode.HTML)
        return

    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <b>/yt_trans &lt;url&gt;</b>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text("⏳ Processing...")
    loading_task = asyncio.create_task(loading_animation(msg))
    final_reply = ""
    
    try:
        data = await call_api("yt-trans", url=context.args[0])
        
        if data and data.get("success"):
            transcript = data.get("transcript", "No transcript found.")
            final_reply = f"📝 <b>YouTube Transcript:</b>\n\n<i>{transcript[:4000]}...</i>" 
            track_command(user_id, "yt_trans", True)
        else:
            error = data.get("error", "Unknown error")
            final_reply = f"❌ <b>Error:</b> {error}"
            track_command(user_id, "yt_trans", False)

    except Exception as e:
        logger.error(f"Unexpected error in handle_yt_trans: {e}")
        final_reply = "❌ An unexpected error occurred."
        track_command(user_id, "yt_trans", False)
    finally:
        loading_task.cancel()
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        await msg.edit_text(f"{final_reply}\n<i>⏱️ {duration}s</i>", parse_mode=ParseMode.HTML)

# --- Main Bot Runner ---

def main() -> None:
    """Run the bot."""
    application = Application.builder().token(YOUR_TELEGRAM_BOT_TOKEN).build()

    # General commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    
    # Admin commands
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("adminhelp", adminhelp))
    
    # Platform handlers
    application.add_handler(CommandHandler("instagram", handle_instagram))
    application.add_handler(CommandHandler("facebook", handle_facebook))
    application.add_handler(CommandHandler("spotify", handle_spotify))
    application.add_handler(CommandHandler("mediafire", handle_mediafire))
    application.add_handler(CommandHandler("x", handle_x))
    application.add_handler(CommandHandler("tiktok", handle_tiktok))
    application.add_handler(CommandHandler("capcut", handle_capcut))
    application.add_handler(CommandHandler("pinterest", handle_pinterest))
    application.add_handler(CommandHandler("youtube", handle_youtube))
    application.add_handler(CommandHandler("soundcloud", handle_soundcloud))
    application.add_handler(CommandHandler("threads", handle_threads))
    application.add_handler(CommandHandler("yt_trans", handle_yt_trans))

    logger.info("🚀 Bot starting...")
    logger.info(f"🔐 Admins configured: {len(ADMIN_IDS)}")
    application.run_polling()

if __name__ == '__main__':
    main()
