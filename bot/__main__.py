import os
import re
import logging
import datetime
import asyncio
import uuid
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from pyrogram import Client, filters, types, idle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import UserNotParticipant, MessageNotModified, FloodWait
import time
from bot.database import Database
from bot import yt_helper
from bot.config import (
    API_ID, API_HASH, BOT_TOKEN, ADMINS, PAID_USERS,
    DEFAULT_UPLOAD_MODE, DEFAULT_SPLIT_SETTING,
    CONTACT_ADMIN, MAX_FILE_SIZE, DOWNLOAD_PATH, TASKS
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create download directory if it doesn't exist
os.makedirs(DOWNLOAD_PATH, exist_ok=True)



# Initialize the bot
app = Client(
    "yt_dlp_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Initialize database
db = Database()

# Active downloads tracking (keyed by url_id)
active_downloads = {}

# Admin cookie waiting flag — per-admin set to avoid race conditions
ADMIN_COOKIE_WAITING = set()

# Command handlers






# Channel/Group IDs — set via environment variables; None means disabled
_ch1 = os.getenv("FORCE_SUB_CHANNEL1", None)
_ch2 = os.getenv("FORCE_SUB_CHANNEL2", None)

def _parse_channel(val):
    """Convert channel value to int if numeric, else keep as string username."""
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return val  # username string like "@mychannel"

FORCE_SUB_CHANNEL1 = _parse_channel(_ch1)
FORCE_SUB_CHANNEL2 = _parse_channel(_ch2)



# Function to check if user is subscribed to a channel
async def is_subscribed(client, user_id, channel_id):
    try:
        await client.get_chat_member(chat_id=channel_id, user_id=user_id)
        return True
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.warning(f"is_subscribed check failed for user {user_id} in {channel_id}: {e}")
        return False

# Function to check subscription status for both channels
async def check_both_subscriptions(client, user_id):
    status = {
        "channel1": await is_subscribed(client, user_id, FORCE_SUB_CHANNEL1) if FORCE_SUB_CHANNEL1 else True,
        "channel2": await is_subscribed(client, user_id, FORCE_SUB_CHANNEL2) if FORCE_SUB_CHANNEL2 else True,
    }
    return status

# Force subscribe function
async def force_subscribe(client, message):
    user_id = message.from_user.id
    
    if not FORCE_SUB_CHANNEL1 and not FORCE_SUB_CHANNEL2:
        return True  # No channels configured, allow all users
    
    try:
        # Check subscription status for both channels
        subscription_status = await check_both_subscriptions(client, user_id)
        
        # If subscribed to both channels, return True
        if subscription_status["channel1"] and subscription_status["channel2"]:
            return True
        
        # Prepare subscription buttons for channels user hasn't joined
        buttons = []
        
        if not subscription_status["channel1"] and FORCE_SUB_CHANNEL1:
            channel_info = await client.get_chat(FORCE_SUB_CHANNEL1)
            channel_name = channel_info.title
            channel_link = f"https://t.me/{channel_info.username}" if channel_info.username else None
            
            if channel_link:
                buttons.append([InlineKeyboardButton(f"📢 Join {channel_name}", url=channel_link)])
        
        if not subscription_status["channel2"] and FORCE_SUB_CHANNEL2:
            channel_info = await client.get_chat(FORCE_SUB_CHANNEL2)
            channel_name = channel_info.title
            channel_link = f"https://t.me/{channel_info.username}" if channel_info.username else None
            
            if channel_link:
                buttons.append([InlineKeyboardButton(f"📢 Join {channel_name}", url=channel_link)])
        
        if buttons:
            buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="check_subscription")])
            await message.reply(
                "**❗ You must join our channels to use this bot!**\n\n"
                "Please join all channels and click the Refresh button below.",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return False  # User not subscribed, block
        else:
            return True  # User subscribed, allow
    except Exception as e:
        logger.error(f"Force Subscribe Error: {e}")
        return True

# Callback query handler for subscription check
@app.on_callback_query(filters.regex("check_subscription"))
async def check_subscription(client, callback_query):
    user_id = callback_query.from_user.id
    message = callback_query.message
    
    # Check if user is banned
    user_data = await db.get_user(user_id)
    if user_data and user_data.get("banned", False):
        await callback_query.answer("You are banned from using this bot.", show_alert=True)
        return
    
    subscription_status = await check_both_subscriptions(client, user_id)
    
    if subscription_status["channel1"] and subscription_status["channel2"]:
        await callback_query.answer("✅ Thank you for subscribing to all channels!", show_alert=True)
        await message.delete()
    else:
        channels_to_join = []
        
        if not subscription_status["channel1"] and FORCE_SUB_CHANNEL1:
            try:
                channel_info = await client.get_chat(FORCE_SUB_CHANNEL1)
                channels_to_join.append(channel_info.title)
            except Exception:
                channels_to_join.append(str(FORCE_SUB_CHANNEL1))
            
        if not subscription_status["channel2"] and FORCE_SUB_CHANNEL2:
            try:
                channel_info = await client.get_chat(FORCE_SUB_CHANNEL2)
                channels_to_join.append(channel_info.title)
            except Exception:
                channels_to_join.append(str(FORCE_SUB_CHANNEL2))
            
        if channels_to_join:
            channels_text = " and ".join(channels_to_join)
            await callback_query.answer(f"❌ You still need to join {channels_text}.", show_alert=True)
        else:
            await callback_query.answer("❌ Please join all required channels.", show_alert=True)









# Base prices for 1-month plans
REGULAR_MONTHLY_PRICE = 30  # ₹30 for regular plan
STUDENT_MONTHLY_PRICE = 10  # ₹10 for student plan

# Discount multipliers for longer durations (slightly discounted for longer commitments)
DURATION_MULTIPLIERS = {
    "1month": 1.0,         # No discount for 1 month
    "3months": 2.85,       # ~5% discount for 3 months (instead of 3.0x)
    "6months": 5.33,       # ~11% discount for 6 months (instead of 6.0x)
    "1year": 10.0          # ~16% discount for 1 year (instead of 12.0x)
}

# Duration display names
DURATION_NAMES = {
    "1month": "1 Month",
    "3months": "3 Months",
    "6months": "6 Months",
    "1year": "1 Year"
}

# Calculate price for a specific plan and duration
def _ensure_aware(dt):
    """Make datetime timezone-aware if it isn't (MongoDB may return tz-naive UTC datetimes)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt

# Calculate price for a specific plan and duration
def calculate_price(base_price, duration):
    multiplier = DURATION_MULTIPLIERS.get(duration, 1.0)
    return int(base_price * multiplier)


# Handler for the /plans command
@app.on_message(filters.command("plans") & filters.private)
async def plans_command(client, message):
    """Display available subscription plans"""
    if not await force_subscribe(client, message):
        return
    
    # Create the initial plans menu
    plans_text = "**📑 Available Subscription Plans 📑**\n\n"
    plans_text += "Choose from our Regular or Student plans below:"
    
    # Create keyboard with two main options
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 Regular", callback_data="show_regular_plans"),
            InlineKeyboardButton("🎓 Student", callback_data="show_student_plans")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_plans")]
    ])
    
    await message.reply(plans_text, reply_markup=keyboard)

    


@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    user_id = message.from_user.id
    username = message.from_user.username

    # Add user to database
    await db.add_user(user_id, username)

    if not await force_subscribe(client, message):
        return

    await message.reply_photo(
        photo="https://d.uguu.se/iatVErRR.jpg",
        caption=(
            f"👋 Hello {message.from_user.mention}!\n\n"
            "ⵊ Aᴍ Tᴇʟᴇɢʀᴀᴍ URL Uᴘʟᴏᴀᴅᴇʀ Bᴏᴛ.\n\n"
            "Sᴇɴᴅ ᴍᴇ ᴀ ᴅɪʀᴇᴄᴛ ʟɪɴᴋ ᴀɴᴅ ɪ ᴡɪʟʟ ᴜᴘʟᴏᴀᴅ ɪᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ ᴀs ᴀ ꜰɪʟᴇ/ᴠɪᴅᴇᴏ\n\n"
            "Usᴇ ʜᴇʟᴘ ʙᴜᴛᴛᴏɴ ᴛᴏ ᴋɴᴏᴡ ʜᴏᴡ ᴛᴏ ᴜsᴇ ᴍᴇ"
        ),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                InlineKeyboardButton("❓ Help", callback_data="help_button")
            ],
            [
                InlineKeyboardButton("📢 Updates", callback_data="updates"),
                InlineKeyboardButton("🛠️ Support", callback_data="support")
            ],
            [InlineKeyboardButton("🍪 Cookie Panel", callback_data="cookie_panel")],
            [InlineKeyboardButton("ℹ️ About", callback_data="about")]
        ])
    )

@app.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    if not await force_subscribe(client, message):
        return
    await message.reply(
        "Aᴠᴀɪʟᴀʙʟᴇ Cᴏᴍᴍᴀɴᴅs:\n\n"
"/start - Sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ\n"
"/help - Sʜᴏᴡ ᴛʜɪs ᴍᴇssᴀɢᴇ\n"
"/settings - Cᴏɴғɪɢᴜʀᴇ ʙᴏᴛ sᴇᴛᴛɪɴɢs\n\n"
"/clearthumbnail - Rᴇᴍᴏᴠᴇ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟ\n"
"/caption - Sᴇᴛ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ (Sᴇɴᴅ ᴡɪᴛʜ ʏᴏᴜʀ ᴄᴀᴘᴛɪᴏɴ ᴛᴇxᴛ)\n"
"/clearcaption - Rᴇᴍᴏᴠᴇ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ\n\n"
"🍪 /cookie - Cᴏᴏᴋɪᴇ Pᴀɴᴇʟ (ʙʏᴘᴀss ʟᴏɢɪɴ ᴡᴀʟʟs)\n\n"
"Jᴜsᴛ Sᴇɴᴅ Tʜᴜᴍʙɴᴀɪʟ ᴛᴏ sᴀᴠᴇ ɪᴛ\n\n"
"Hᴏᴡ ᴛᴏ ᴜsᴇ:\n"
"Sɪᴍᴘʟʏ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ URL, ᴀɴᴅ I'ʟʟ ғᴇᴛᴄʜ ᴛʜᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ғᴏʀᴍᴀᴛs ғᴏʀ ʏᴏᴜ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back", callback_data="back_to_start")]
        ])
    )

@app.on_message(filters.command("settings") & filters.private)
async def settings_command(client, message):
    if not await force_subscribe(client, message):
        return
    user_id = message.from_user.id
    user_data = await db.get_user(user_id)
    
    if not user_data:
        await db.add_user(user_id, message.from_user.username)
        user_data = await db.get_user(user_id) or {}
    
    # Check if user is banned
    if user_data.get("banned", False):
        await message.reply("You are banned from using this bot.")
        return
    
    # Get user settings
    upload_mode = user_data.get("upload_mode", DEFAULT_UPLOAD_MODE)
    split_enabled = user_data.get("split_enabled", DEFAULT_SPLIT_SETTING)
    caption_enabled = user_data.get("caption_enabled", False)
    generate_screenshots = user_data.get("generate_screenshots", False)
    generate_sample_video = user_data.get("generate_sample_video", False)
    
    # Create settings markup
    settings_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"Upload as: {'Video' if upload_mode == 'video' else 'File'}", 
                callback_data="toggle_upload_mode"
            )
        ],
        [
            InlineKeyboardButton(
                f"Split files: {'Enabled' if split_enabled else 'Disabled'}", 
                callback_data="toggle_split"
            )
        ],
        [
            InlineKeyboardButton(
                f"Caption: {'Enabled' if caption_enabled else 'Disabled'}", 
                callback_data="toggle_caption"
            )
        ],
        [
            InlineKeyboardButton(
                f"Screenshots: {'Enabled' if generate_screenshots else 'Disabled'}", 
                callback_data="toggle_screenshots"
            )
        ],
        [
            InlineKeyboardButton(
                f"Sample Video: {'Enabled' if generate_sample_video else 'Disabled'}", 
                callback_data="toggle_sample_video"
            )
        ],
        [
            
            InlineKeyboardButton("Close", callback_data="close_settings")
        ]
    ])
    
    await message.reply(
        "**Bot Settings**\n\n"
        f"Upload Mode: {'Video' if upload_mode == 'video' else 'File'}\n"
        f"Split Files: {'Enabled' if split_enabled else 'Disabled'}\n"
        f"Custom Caption: {'Enabled' if caption_enabled else 'Disabled'}\n"
        f"Generate Screenshots: {'Enabled' if generate_screenshots else 'Disabled'}\n"
        f"Generate Sample Video: {'Enabled' if generate_sample_video else 'Disabled'}",
        reply_markup=settings_markup
    )

@app.on_message(filters.photo & filters.private)
async def save_thumbnail(client, message):
    user_id = message.from_user.id
    user_data = await db.get_user(user_id)
    
    if not user_data:
        await db.add_user(user_id, message.from_user.username)
        user_data = await db.get_user(user_id) or {}
    
    if user_data.get("banned", False):
        return  # Silently ignore banned users
    
    # Get the photo file_id
    photo = message.photo.file_id
    
    # Save to database
    success = await db.set_thumbnail(user_id, photo)
    
    if success:
        await message.reply("✅ Thumbnail saved successfully!")
    else:
        await message.reply("❌ Failed to set thumbnail. Please try again.")





@app.on_message(filters.command("clearthumbnail") & filters.private)
async def clear_thumbnail(client, message):
    user_id = message.from_user.id
    user_data = await db.get_user(user_id)
    if user_data and user_data.get("banned", False):
        await message.reply("You are banned from using this bot.")
        return
    
    # Remove thumbnail from database
    success = await db.set_thumbnail(user_id, None)
    
    if success:
        await message.reply("✅ Custom thumbnail has been removed.")
    else:
        await message.reply("❌ Failed to remove thumbnail. Please try again.")

@app.on_message(filters.command("caption") & filters.private)
async def set_caption(client, message):
    user_id = message.from_user.id
    user_data = await db.get_user(user_id)
    if user_data and user_data.get("banned", False):
        await message.reply("You are banned from using this bot.")
        return
    
    # Check if there's caption text
    if len(message.command) < 2:
        await message.reply(
            "Please provide a caption text.\n\n"
            "Example: `/caption Your custom caption here`"
        )
        return
    
    # Get caption text (message.command[1:] handles @botname correctly)
    caption = " ".join(message.command[1:])
    
    # Save to database
    success = await db.set_caption(user_id, caption)
    await db.update_user_settings(user_id, {"caption_enabled": True})
    
    if success:
        await message.reply(
            f"✅ Custom caption has been set successfully!\n\n"
            f"Your caption: {caption}"
        )
    else:
        await message.reply("❌ Failed to set caption. Please try again.")

@app.on_message(filters.command("clearcaption") & filters.private)
async def clear_caption(client, message):
    user_id = message.from_user.id
    user_data = await db.get_user(user_id)
    if user_data and user_data.get("banned", False):
        await message.reply("You are banned from using this bot.")
        return
    
    # Remove caption from database
    success = await db.delete_caption(user_id)
    
    if success:
        await message.reply("✅ Custom caption has been removed.")
    else:
        await message.reply("❌ Failed to remove caption. Please try again.")


# ─────────────────────────────────────────────────────────────────────────────
# COOKIE PANEL
# /cookie  → all users can open panel, only admin buttons work
# /setcookie, /delcookie, /cookiestatus → admin only
# ─────────────────────────────────────────────────────────────────────────────

@app.on_message(filters.command("cookie") & filters.private)
async def cookie_panel(client, message):
    """Cookie panel - visible to all users, manageable only by admin"""
    cookies = await db.get_global_cookies()
    has_cookies = bool(cookies and cookies.strip())
    lines = len(cookies.strip().splitlines()) if has_cookies else 0

    if has_cookies:
        status_text = f"✅ **Cookies Active** — {lines} lines loaded\nDownloads from restricted sites will work."
    else:
        status_text = "❌ **No cookies set.**\nRestricted sites may not work until admin adds cookies."

    text = (
        "🍪 **Cookie Control Panel**\n\n"
        "Cookies allow this bot to bypass login walls and age restrictions for:\n"
        "• YouTube  • Instagram  • TikTok  • Twitter/X  • Hotstar & more\n\n"
        f"**Status:** {status_text}"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Cookies", callback_data="admin_cookie_set"),
         InlineKeyboardButton("🗑 Delete Cookies", callback_data="admin_cookie_del")],
        [InlineKeyboardButton("🔄 Refresh Status", callback_data="cookie_refresh")],
    ])

    await message.reply(text, reply_markup=keyboard)


@app.on_message(filters.command("setcookie") & filters.user(ADMINS) & filters.private)
async def admin_setcookie(client, message):
    """Admin: set global cookies"""
    global ADMIN_COOKIE_WAITING
    ADMIN_COOKIE_WAITING.add(message.from_user.id)
    await message.reply(
        "📂 **Send me the `cookies.txt` file now.**\n\n"
        "Must be **Netscape HTTP Cookie File** format.\n\n"
        "How to export:\n"
        "1. Install **Cookie-Editor** browser extension\n"
        "2. Login to the target website\n"
        "3. Cookie-Editor → **Export → Export as Netscape**\n"
        "4. Save as `.txt` and send here\n\n"
        "⏳ Waiting for file..."
    )


@app.on_message(filters.command("delcookie") & filters.user(ADMINS) & filters.private)
async def admin_delcookie(client, message):
    """Admin: delete global cookies"""
    global ADMIN_COOKIE_WAITING
    ADMIN_COOKIE_WAITING.discard(message.from_user.id)
    success = await db.delete_global_cookies()
    if success:
        await message.reply("🗑 **Global cookies deleted.**\nAll downloads will proceed without cookies.")
    else:
        await message.reply("❌ Failed to delete cookies.")


@app.on_message(filters.command("cookiestatus") & filters.user(ADMINS) & filters.private)
async def admin_cookiestatus(client, message):
    """Admin: check cookie status"""
    cookies = await db.get_global_cookies()
    if cookies and cookies.strip():
        lines = len(cookies.strip().splitlines())
        await message.reply(
            f"✅ **Global cookies ACTIVE**\n"
            f"📄 Lines: **{lines}**\n\n"
            f"All downloads use these cookies.\n"
            f"/delcookie to remove."
        )
    else:
        await message.reply("❌ **No global cookies.**\nUse /setcookie to upload.")


@app.on_message(filters.document & filters.user(ADMINS) & filters.private, group=-1)
async def admin_handle_cookie_file(client, message):
    """Admin: receive cookies.txt file"""
    global ADMIN_COOKIE_WAITING
    if message.from_user.id not in ADMIN_COOKIE_WAITING:
        return

    ADMIN_COOKIE_WAITING.discard(message.from_user.id)
    status_msg = await message.reply("⏳ Processing cookies file...")

    try:
        file_path = await client.download_media(message.document, file_name="/tmp/admin_cookies.txt")
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            cookies_content = f.read()

        if not cookies_content.strip():
            await status_msg.edit("❌ File is empty. Send a valid cookies.txt file.")
            try:
                os.remove(file_path)
            except Exception:
                pass
            return

        has_header = "HTTP Cookie File" in cookies_content or "Netscape" in cookies_content
        has_tabs = "\t" in cookies_content
        if not has_header and not has_tabs:
            await status_msg.edit(
                "❌ **Invalid format!**\n\n"
                "File must be **Netscape HTTP Cookie File** format.\n\n"
                "How to export:\n"
                "1. Install **Cookie-Editor** browser extension\n"
                "2. Login to the site\n"
                "3. Cookie-Editor → **Export → Export as Netscape**\n\n"
                "Use /setcookie to try again."
            )
            try:
                os.remove(file_path)
            except Exception:
                pass
            return

        success = await db.set_global_cookies(cookies_content)
        try:
            os.remove(file_path)
        except Exception:
            pass

        if success:
            lines = len(cookies_content.strip().splitlines())
            await status_msg.edit(
                f"✅ **Cookies saved successfully!**\n"
                f"📄 Lines: **{lines}**\n\n"
                f"All downloads will now use these cookies.\n"
                f"Use /delcookie to remove  |  /cookiestatus to check."
            )
        else:
            await status_msg.edit("❌ Failed to save cookies to database. Try again.")

    except Exception as e:
        logger.error(f"Error processing admin cookie file: {e}")
        await status_msg.edit(f"❌ Error: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
# END COOKIE PANEL
# ─────────────────────────────────────────────────────────────────────────────

# Admin commands
@app.on_message(filters.command("broadcast") & filters.user(ADMINS))
async def broadcast(client, message):
    if len(message.command) < 2:
        await message.reply("Please provide a message to broadcast.")
        return
    
    broadcast_message = (message.text or message.caption or "").split(None, 1)[1] if len((message.text or message.caption or "").split(None, 1)) > 1 else ""
    if not broadcast_message.strip():
        await message.reply("Could not extract broadcast message text.")
        return
    users = await db.get_all_users()
    
    sent = 0
    failed = 0
    status_msg = await message.reply("Broadcasting message...")
    
    for user in users:
        try:
            await client.send_message(user["user_id"], broadcast_message)
            sent += 1
            # Update status every 20 messages
            if sent % 20 == 0:
                await status_msg.edit(f"Broadcasting message...\nSent: {sent}\nFailed: {failed}")
            await asyncio.sleep(0.1)  # Small delay to avoid flood
        except FloodWait as e:
            logger.warning(f"FloodWait: sleeping {e.value}s")
            await asyncio.sleep(e.value)
            try:
                await client.send_message(user["user_id"], broadcast_message)
                sent += 1
            except Exception as retry_e:
                logger.error(f"Failed to broadcast to {user['user_id']} after FloodWait: {retry_e}")
                failed += 1
        except Exception as e:
            logger.error(f"Failed to broadcast to {user['user_id']}: {e}")
            failed += 1
    
    await status_msg.edit(f"✅ Broadcast completed!\nSent: {sent}\nFailed: {failed}")

@app.on_message(filters.command("ban") & filters.user(ADMINS))
async def ban_user(client, message):
    if len(message.command) < 2:
        await message.reply("Please provide a user ID to ban.")
        return
    
    try:
        user_id = int(message.command[1])
        success = await db.ban_user(user_id, True)
        
        if success:
            await message.reply(f"✅ User {user_id} has been banned.")
        else:
            await message.reply(f"❌ Failed to ban user {user_id}.")
    except ValueError:
        await message.reply("Please provide a valid user ID.")



# Helper function to format duration for display
def format_time_remaining(days):
    if days <= 0:
        return "Expired"
    elif days == 1:
        return "1 day"
    elif days < 30:
        return f"{days} days"
    elif days < 365:
        months = days // 30
        remaining_days = days % 30
        if months == 1:
            month_text = "1 month"
        else:
            month_text = f"{months} months"
            
        if remaining_days > 0:
            return f"{month_text} and {remaining_days} days"
        return month_text
    else:
        years = days // 365
        remaining_days = days % 365
        if years == 1:
            year_text = "1 year"
        else:
            year_text = f"{years} years"
            
        if remaining_days > 30:
            months = remaining_days // 30
            if months == 1:
                return f"{year_text} and 1 month"
            else:
                return f"{year_text} and {months} months"
        return year_text

# Notification function
async def notify_user_about_subscription(client, user_id, expiry_date, is_new=True):
    """
    Send notification to user about their subscription status
    
    Parameters:
    - client: Bot client instance
    - user_id: User ID to notify
    - expiry_date: When the subscription expires
    - is_new: Whether this is a new subscription or renewal
    """
    start_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_date = expiry_date.strftime("%Y-%m-%d %H:%M:%S") if expiry_date else "No expiry"
    
    # Calculate subscription duration for display
    days_remaining = (_ensure_aware(expiry_date) - datetime.datetime.now(datetime.timezone.utc)).days if expiry_date else 0
    duration_text = format_time_remaining(days_remaining)
    
    action = "started" if is_new else "renewed"
    
    text_body = f"🎉 **Premium Subscription {action}!** 🎉\n\n"
    text_body += f"📅 **Started on:** {start_date}\n"
    text_body += f"📅 **Ending on:** {end_date}\n"
    text_body += f"⏱️ **Duration:** {duration_text}\n\n"
    text_body += "✨ Enjoy the bot and all premium features! ✨\n\n"
    text_body += "Use /upgrade command anytime to check your subscription status."
    
    try:
        await client.send_message(chat_id=user_id, text=text_body)
        logger.info(f"Subscription notification sent to user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send subscription notification to user {user_id}: {e}")
        return False

# Add paid user command
@app.on_message(filters.command("addpaid") & filters.user(ADMINS))
async def add_paid_user(client, message):
    if len(message.command) < 2:
        await message.reply("Please provide a user ID and optional expiry duration.\nFormat: /addpaid <user_id> [duration]\nExample: /addpaid 12456767 36d")
        return
    
    try:
        user_id = int(message.command[1])
        
        # Check if expiry duration is provided
        expiry_date = None
        if len(message.command) >= 3:
            duration_str = message.command[2]
            
            # Parse the duration (e.g., "36d", "2m", "1y")
            duration_match = re.fullmatch(r"(\d+)([dmy])", duration_str)
            if duration_match:
                amount = int(duration_match.group(1))
                unit = duration_match.group(2)
                
                now = datetime.datetime.now(datetime.timezone.utc)
                
                if unit == "d":
                    expiry_date = now + datetime.timedelta(days=amount)
                elif unit == "m":
                    expiry_date = now + datetime.timedelta(days=amount * 30)  # Approximate months
                elif unit == "y":
                    expiry_date = now + datetime.timedelta(days=amount * 365)  # Approximate years
            
            if not expiry_date:
                await message.reply("Invalid duration format. Please use format like 30d (30 days), 2m (2 months), or 1y (1 year).")
                return
        
        # Check if user exists in database
        user_data = await db.get_user(user_id)
        if not user_data:
            await message.reply(f"⚠️ User {user_id} not found in database. Adding user...")
            await db.add_user(user_id, None)  # username unknown at this point
            user_data = await db.get_user(user_id) or {}  # re-fetch after adding
        
        # Check if user was already a paid user (to determine if this is new subscription or renewal)
        # Determine if this is a new subscription or renewal
        is_new_subscription = not user_data.get("is_paid", False)
        
        # Update the database with the paid status and expiry date
        success = await db.set_paid_status(user_id, True, expiry_date)
        
        if success:
            # Format expiry date for display
            expiry_msg = f" until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}" if expiry_date else ""
            duration_text = format_time_remaining((_ensure_aware(expiry_date) - datetime.datetime.now(datetime.timezone.utc)).days) if expiry_date else "indefinitely"
            
            await message.reply(f"✅ User {user_id} has been added as a paid user {expiry_msg}.\nSubscription duration: {duration_text}")
            
            # Notify the user about their subscription
            if expiry_date:
                notification_sent = await notify_user_about_subscription(client, user_id, expiry_date, is_new=is_new_subscription)
                if not notification_sent:
                    await message.reply(f"⚠️ Failed to send notification to user {user_id}. They might have blocked the bot.")
        else:
            await message.reply(f"❌ Failed to add user {user_id} as paid user.")
    except ValueError:
        await message.reply("Please provide a valid user ID.")

# Remove paid status command
@app.on_message(filters.command("removepaid") & filters.user(ADMINS))
async def remove_paid_user(client, message):
    if len(message.command) < 2:
        await message.reply("Please provide a user ID to remove paid status.\nFormat: /removepaid <user_id>")
        return
    
    try:
        user_id = int(message.command[1])
        
        # Get user data
        user_data = await db.get_user(user_id)
        if not user_data:
            await message.reply(f"❌ User {user_id} not found in database.")
            return
            
        if not user_data.get("is_paid", False):
            await message.reply(f"⚠️ User {user_id} is not a paid user.")
            return
        
        # Remove paid status
        success = await db.set_paid_status(user_id, False, None)
        
        if success:
            await message.reply(f"✅ Paid status removed from user {user_id}.")
            
            # Notify the user
            try:
                await client.send_message(
                    chat_id=user_id,
                    text="⚠️ **Your premium subscription has been cancelled.**\n\nYou no longer have access to premium features.\nContact an admin if you believe this is a mistake."
                )
            except Exception as e:
                await message.reply(f"⚠️ Failed to send notification to user {user_id}: {e}")
        else:
            await message.reply(f"❌ Failed to remove paid status from user {user_id}.")
    except ValueError:
        await message.reply("Please provide a valid user ID.")

# Command to check subscription status
@app.on_message(filters.command("upgrade") & filters.private)
async def check_subscription_status(client, message):
    """Command to let users check their subscription status"""
    user_id = message.from_user.id
    
    # Get user data and ensure expiry is checked
    user_data = await db.get_user(user_id)
    
    if not user_data:
        # User not in database, add them
        await db.add_user(user_id, message.from_user.username)
        user_data = await db.get_user(user_id) or {}
    
    if user_data.get("is_paid", False):
        # User has an active subscription
        if "paid_expiry" in user_data and user_data["paid_expiry"]:
            days_left = (_ensure_aware(user_data["paid_expiry"]) - datetime.datetime.now(datetime.timezone.utc)).days
            expiry_date = user_data["paid_expiry"].strftime("%Y-%m-%d %H:%M:%S")
            _sub_start = user_data.get("subscription_start")
            if isinstance(_sub_start, datetime.datetime):
                start_date = _ensure_aware(_sub_start).strftime("%Y-%m-%d %H:%M:%S")
            else:
                start_date = "Unknown"
            duration_text = format_time_remaining(days_left)
            
            response = f"✅ **You have an active premium subscription!**\n\n"
            response += f"📅 **Started on:** {start_date}\n"
            response += f"📅 **Expires on:** {expiry_date}\n"
            response += f"⏱️ **Time remaining:** {duration_text}\n\n"
            
            if days_left < 7:
                response += "⚠️ Your subscription is ending soon. Contact an admin to renew."
            else:
                response += "Enjoy using all premium features of the bot!"
        else:
            response = "✅ **You have an active premium subscription without expiration!**\n\n"
            response += "Enjoy using all premium features of the bot!"
    else:
        # User doesn't have an active subscription
        response = "❌ **You don't have an active premium subscription.**\n\n"
        response += "Get premium to access exclusive features:\n"
        response += "• Upload larger files\n"
        response += "• Higher processing speed\n"
        response += "• Custom thumbnail support\n"
        response += "• Priority support\n\n"
        response += "Contact an admin to purchase a subscription."
    
    await message.reply(response)

# Command to list all paid users (for admins)
@app.on_message(filters.command("paidusers") & filters.user(ADMINS))
async def list_paid_users(client, message):
    """List all users with active paid subscriptions"""
    # Get current paid users (this automatically checks and updates expired subscriptions)
    paid_users = await db.get_paid_users()
    
    if not paid_users:
        await message.reply("No active paid users found.")
        return
    
    now = datetime.datetime.now(datetime.timezone.utc)
    header = f"📊 **Active Paid Users: {len(paid_users)}**\n\n"
    
    entries = []
    for i, user in enumerate(paid_users, 1):
        user_id = user["user_id"]
        username = user.get("username", "")
        username_text = f" (@{username})" if username else ""
        
        if "paid_expiry" in user and user["paid_expiry"]:
            days_left = (_ensure_aware(user["paid_expiry"]) - now).days
            expiry_date = user["paid_expiry"].strftime("%Y-%m-%d")
            entries.append(f"{i}. User ID: `{user_id}`{username_text}\n   Expires: {expiry_date} ({days_left} days left)\n")
        else:
            entries.append(f"{i}. User ID: `{user_id}`{username_text}\n   No expiration date\n")
    
    # Split into chunks to stay within Telegram 4096 char limit
    chunk = header
    for entry in entries:
        if len(chunk) + len(entry) + 1 > 4000:
            await message.reply(chunk)
            chunk = entry
        else:
            chunk += "\n" + entry
    if chunk:
        await message.reply(chunk)



@app.on_message(filters.command("unban") & filters.user(ADMINS))
async def unban_user(client, message):
    if len(message.command) < 2:
        await message.reply("Please provide a user ID to unban.")
        return
    
    try:
        user_id = int(message.command[1])
        success = await db.ban_user(user_id, False)
        
        if success:
            await message.reply(f"✅ User {user_id} has been unbanned.")
        else:
            await message.reply(f"❌ Failed to unban user {user_id}.")
    except ValueError:
        await message.reply("Please provide a valid user ID.")
        

@app.on_message(filters.text & ~filters.document & filters.regex(yt_helper.URL_PATTERN) & filters.private)
async def url_handler(client, message):
    # If admin is in cookie-waiting mode, ignore URL messages
    global ADMIN_COOKIE_WAITING
    if message.from_user.id in ADMIN_COOKIE_WAITING and message.from_user.id in ADMINS:
        return

    user_id = message.from_user.id
    user_data = await db.get_user(user_id)
    
    # Check if user exists and is not banned
    if not user_data:
        await db.add_user(user_id, message.from_user.username)
        user_data = await db.get_user(user_id) or {}
    
    if user_data.get("banned", False):
        await message.reply("You are banned from using this bot.")
        return

    # Force subscribe check
    if not await force_subscribe(client, message):
        return

    # Check if user is paid
    is_paid = user_data.get("is_paid", False) or user_id in PAID_USERS
    
    # If user is not paid and not admin, check daily limit
    if not is_paid and user_id not in ADMINS:
        # Get current task count
        task_count = await db.get_daily_task_count(user_id)
        
        # Check if user has reached daily limit 
        if task_count >= TASKS:
            await message.reply(
                f"⚠️ You have reached your daily limit of {TASKS} downloads.\n\n"
                "Please try again tomorrow or upgrade to a paid plan /plans for unlimited downloads.\n\n"
                f"Contact: {CONTACT_ADMIN}\n\nor Contact @anujedits76"
            )
            return
    
    # Check if URL is valid
    url = (message.text or "").strip()
    if not url or not yt_helper.is_valid_url(url):
        await message.reply("❌ Invalid URL. Please send a valid YTDL-supported URL.")
        return
    
    # Check if there's already an active download for this user
    user_has_active = any(
        v.get("user_id") == user_id for v in active_downloads.values()
        if isinstance(v, dict)
    )
    if user_has_active:
        await message.reply("⚠️ You already have an active download. Please wait for it to complete.")
        return
    
    # Create a unique ID for this URL
    url_id = str(uuid.uuid4())
    
    # Store URL in database
    await db.store_url(url_id, url, user_id)
    
    # Send initial processing message (task count NOT incremented yet)
    if not is_paid and user_id not in ADMINS:
        existing_count = await db.get_daily_task_count(user_id)
        tasks_remaining = TASKS - existing_count
        processing_msg = await message.reply(
            f"🔍 Processing URL... Please wait.\n\n"
            f"📊 You have used {existing_count}/{TASKS} downloads today. {tasks_remaining} remaining."
        )
    else:
        processing_msg = await message.reply("🔍 Processing URL... Please wait.")
    
    try:
        # Get admin global cookies for this download
        global_cookies = await db.get_global_cookies()
        video_info = await yt_helper.get_video_info(url, cookies_content=global_cookies)
        
        if not video_info:
            await processing_msg.edit("❌ Failed to fetch video information. Make sure the URL is valid and supported.")
            return
        
        # Prepare format buttons
        format_buttons = []
        for fmt in video_info.get('formats', []):
            if fmt.get('format_id') and fmt.get('resolution'):
                size_info = f" | {fmt['size_str']}" if fmt.get('size_str') else ""
                btn_text = f"{fmt['resolution']} ({fmt['ext']}){size_info}"
                # Truncate format_id to keep callback_data within Telegram's 64-char limit
                # "dl|" (3) + url_id (36) + "|" (1) = 40 chars used; 24 chars left for format_id
                safe_fmt_id = fmt['format_id'][:24]
                callback_data = f"dl|{url_id}|{safe_fmt_id}"
                format_buttons.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
        
        if not format_buttons:
            await processing_msg.edit("❌ No downloadable formats found for this URL.")
            return
        
        # Add cancel button
        format_buttons.append([InlineKeyboardButton("Cancel", callback_data=f"cancel|{url_id}")])
        
        # Create markup
        format_markup = InlineKeyboardMarkup(format_buttons)
        
        vi_title = video_info.get('title', 'Unknown')
        vi_uploader = video_info.get('uploader', 'Unknown')
        vi_duration = video_info.get('duration', 0)

        # Video info fetched successfully — NOW increment task count
        if not is_paid and user_id not in ADMINS:
            task_count = await db.track_daily_task(user_id)
            tasks_remaining = TASKS - task_count
            
            await processing_msg.edit(
                f"📹 **{vi_title}**\n\n"
                f"👤 **Uploader:** {vi_uploader}\n"
                f"⏱️ **Duration:** {format_duration(vi_duration)}\n\n"
                f"📊 You have used {task_count}/{TASKS} downloads today. {tasks_remaining} remaining.\n\n"
                f"Please select a format to download:",
                reply_markup=format_markup
            )
        else:
            await processing_msg.edit(
                f"📹 **{vi_title}**\n\n"
                f"👤 **Uploader:** {vi_uploader}\n"
                f"⏱️ **Duration:** {format_duration(vi_duration)}\n\n"
                f"Please select a format to download:",
                reply_markup=format_markup
            )
    except Exception as e:
        logger.error(f"Error processing URL: {e}")
        await processing_msg.edit(f"❌ An error occurred: {str(e)}")



# Callback query handler
@app.on_callback_query()
async def callback_handler(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data
    message = callback_query.message
    
    # Get user data
    user_data = await db.get_user(user_id)
    if not user_data:
        await callback_query.answer("User not found in database.")
        return
    
    # Check if user is banned
    if user_data.get("banned", False):
        await callback_query.answer("You are banned from using this bot.")
        return
    
    global ADMIN_COOKIE_WAITING

    # ── Cookie panel callbacks ────────────────────────────────────────────────
    if data == "cookie_panel":
        cookies = await db.get_global_cookies()
        has_cookies = bool(cookies and cookies.strip())
        lines = len(cookies.strip().splitlines()) if has_cookies else 0
        if has_cookies:
            status_text = f"✅ **Cookies Active** — {lines} lines loaded\nDownloads from restricted sites will work."
        else:
            status_text = "❌ **No cookies set.**\nRestricted sites may not work until admin adds cookies."
        text = (
            "🍪 **Cookie Control Panel**\n\n"
            "Cookies allow this bot to bypass login walls and age restrictions for:\n"
            "• YouTube  • Instagram  • TikTok  • Twitter/X  • Hotstar & more\n\n"
            f"**Status:** {status_text}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Cookies", callback_data="admin_cookie_set"),
             InlineKeyboardButton("🗑 Delete Cookies", callback_data="admin_cookie_del")],
            [InlineKeyboardButton("🔄 Refresh Status", callback_data="cookie_refresh")],
        ])
        await callback_query.answer()
        try:
            await message.edit(text, reply_markup=keyboard)
        except Exception:
            await message.reply(text, reply_markup=keyboard)
        return

    if data == "cookie_refresh":
        cookies = await db.get_global_cookies()
        has_cookies = bool(cookies and cookies.strip())
        lines = len(cookies.strip().splitlines()) if has_cookies else 0
        status_text = f"✅ **Cookies Active** — {lines} lines loaded\nDownloads from restricted sites will work." if has_cookies else "❌ **No cookies set.**\nRestricted sites may not work until admin adds cookies."
        text = (
            "🍪 **Cookie Control Panel**\n\n"
            "Cookies allow this bot to bypass login walls and age restrictions for:\n"
            "• YouTube  • Instagram  • TikTok  • Twitter/X  • Hotstar & more\n\n"
            f"**Status:** {status_text}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Cookies", callback_data="admin_cookie_set"),
             InlineKeyboardButton("🗑 Delete Cookies", callback_data="admin_cookie_del")],
            [InlineKeyboardButton("🔄 Refresh Status", callback_data="cookie_refresh")],
        ])
        await callback_query.answer("✅ Refreshed!" if has_cookies else "❌ No cookies set.")
        try:
            await message.edit(text, reply_markup=keyboard)
        except Exception:
            pass
        return

    if data == "admin_cookie_set":
        if user_id not in ADMINS:
            await callback_query.answer("❌ Only admin can manage cookies.", show_alert=True)
            return
        ADMIN_COOKIE_WAITING.add(user_id)
        await callback_query.answer()
        await message.reply(
            "📂 **Send me the `cookies.txt` file now.**\n\n"
            "Must be **Netscape HTTP Cookie File** format.\n\n"
            "How to export:\n"
            "1. Install **Cookie-Editor** browser extension\n"
            "2. Login to the target website\n"
            "3. Cookie-Editor → **Export → Export as Netscape**\n"
            "4. Save as `.txt` and send here\n\n"
            "⏳ Waiting for file..."
        )
        return

    if data == "admin_cookie_del":
        if user_id not in ADMINS:
            await callback_query.answer("❌ Only admin can manage cookies.", show_alert=True)
            return
        ADMIN_COOKIE_WAITING.discard(user_id)
        success = await db.delete_global_cookies()
        if success:
            await callback_query.answer("🗑 Cookies deleted!", show_alert=True)
            try:
                await message.edit(
                    "🍪 **Cookie Control Panel**\n\n"
                    "**Status:** ❌ No cookies set.\n\n"
                    "Admin: use buttons to manage cookies.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Add Cookies", callback_data="admin_cookie_set"),
                         InlineKeyboardButton("🗑 Delete Cookies", callback_data="admin_cookie_del")],
                        [InlineKeyboardButton("🔄 Refresh Status", callback_data="cookie_refresh")],
                    ])
                )
            except MessageNotModified:
                pass
        else:
            await callback_query.answer("❌ Failed to delete.", show_alert=True)
        return
    # ── End cookie callbacks ──────────────────────────────────────────────────

    # Handle settings callbacks
    elif data == "settings":
        await callback_query.answer("Opening settings...")
        upload_mode = user_data.get("upload_mode", DEFAULT_UPLOAD_MODE)
        split_enabled = user_data.get("split_enabled", DEFAULT_SPLIT_SETTING)
        caption_enabled = user_data.get("caption_enabled", False)
        generate_screenshots = user_data.get("generate_screenshots", False)
        generate_sample_video = user_data.get("generate_sample_video", False)
    
        # Create settings markup
        settings_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"Upload as: {'Video' if upload_mode == 'video' else 'File'}", 
                    callback_data="toggle_upload_mode"
                )
            ],
            [
                InlineKeyboardButton(
                    f"Split files: {'Enabled' if split_enabled else 'Disabled'}", 
                    callback_data="toggle_split"
                )
            ],
            [
                InlineKeyboardButton(
                    f"Caption: {'Enabled' if caption_enabled else 'Disabled'}", 
                    callback_data="toggle_caption"
                )
            ],
            [
                InlineKeyboardButton(
                    f"Screenshots: {'Enabled' if generate_screenshots else 'Disabled'}", 
                    callback_data="toggle_screenshots"
                )
            ],
            [
                InlineKeyboardButton(
                    f"Sample Video: {'Enabled' if generate_sample_video else 'Disabled'}", 
                    callback_data="toggle_sample_video"
                )
            ],
            [
                InlineKeyboardButton("◀️ Back", callback_data="back_to_start"),
                InlineKeyboardButton("Close", callback_data="close_settings")
            ]
        ])
    
        try:
            await message.edit(
                "**Bot Settings**\n\n"
                f"Upload Mode: {'Video' if upload_mode == 'video' else 'File'}\n"
                f"Split Files: {'Enabled' if split_enabled else 'Disabled'}\n"
                f"Custom Caption: {'Enabled' if caption_enabled else 'Disabled'}\n"
                f"Generate Screenshots: {'Enabled' if generate_screenshots else 'Disabled'}\n"
                f"Generate Sample Video: {'Enabled' if generate_sample_video else 'Disabled'}",
                reply_markup=settings_markup
            )
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Settings edit error: {e}")
        return
    
    elif data == "toggle_upload_mode":
        current_mode = user_data.get("upload_mode", DEFAULT_UPLOAD_MODE)
        new_mode = "file" if current_mode == "video" else "video"
        await db.update_user_settings(user_id, {"upload_mode": new_mode})
        
        await callback_query.answer(f"Upload mode changed to: {new_mode}")
        
        # Update settings message
        await update_settings_message(client, message, user_id)
        return
    
    elif data == "toggle_split":
        current_setting = user_data.get("split_enabled", DEFAULT_SPLIT_SETTING)
        await db.update_user_settings(user_id, {"split_enabled": not current_setting})
        
        await callback_query.answer(f"Split setting: {'Disabled' if current_setting else 'Enabled'}")
        
        # Update settings message
        await update_settings_message(client, message, user_id)
        return
    
    elif data == "toggle_caption":
        current_setting = user_data.get("caption_enabled", False)
        await db.update_user_settings(user_id, {"caption_enabled": not current_setting})
        
        if not current_setting and not user_data.get("caption"):
            await callback_query.answer("Caption enabled. Use /caption to set your caption.")
        else:
            await callback_query.answer(f"Caption: {'Disabled' if current_setting else 'Enabled'}")
        
        # Update settings message
        await update_settings_message(client, message, user_id)
        return
    
    elif data == "toggle_screenshots":
        current_setting = user_data.get("generate_screenshots", False)
        await db.update_user_settings(user_id, {"generate_screenshots": not current_setting})
        
        await callback_query.answer(f"Screenshots: {'Disabled' if current_setting else 'Enabled'}")
        
        # Update settings message
        await update_settings_message(client, message, user_id)
        return
    
    elif data == "toggle_sample_video":
        current_setting = user_data.get("generate_sample_video", False)
        await db.update_user_settings(user_id, {"generate_sample_video": not current_setting})
        
        await callback_query.answer(f"Sample video: {'Disabled' if current_setting else 'Enabled'}")
        
        # Update settings message
        await update_settings_message(client, message, user_id)
        return


    # Handle help button
    elif data == "help_button":
        await callback_query.answer("Opening help...")
        try:
            await message.edit(
                "**Aᴠᴀɪʟᴀʙʟᴇ Cᴏᴍᴍᴀɴᴅs:**\n\n"
                "/start - Sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ\n"
                "/help - Sʜᴏᴡ ᴛʜɪs ᴍᴇssᴀɢᴇ\n"
                "/settings - Cᴏɴғɪɢᴜʀᴇ ʙᴏᴛ sᴇᴛᴛɪɴɢs\n"
                "/clearthumbnail - Rᴇᴍᴏᴠᴇ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟ\n"
                "/caption - Sᴇᴛ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ (Sᴇɴᴅ ᴡɪᴛʜ ʏᴏᴜʀ ᴄᴀᴘᴛɪᴏɴ ᴛᴇxᴛ)\n"
                "/clearcaption - Rᴇᴍᴏᴠᴇ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ\n\n"
                "Jᴜsᴛ Sᴇɴᴅ Tʜᴜᴍʙɴᴀɪʟ ᴛᴏ sᴀᴠᴇ ɪᴛ\n\n"
                "**Hᴏᴡ ᴛᴏ ᴜsᴇ:**\n"
                "Sɪᴍᴘʟʏ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ URL, ᴀɴᴅ I'ʟʟ ғᴇᴛᴄʜ ᴛʜᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ғᴏʀᴍᴀᴛs ғᴏʀ ʏᴏᴜ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Back", callback_data="back_to_start")]
                ])
            )
        except MessageNotModified:
            pass
        return

    # Handle back to start
    elif data == "back_to_start":
        await callback_query.answer("Returning to start menu...")
        try:
            await message.edit(
                f"👋 Hello {callback_query.from_user.mention}!\n\n"
                f"ⵊ Aᴍ Tᴇʟᴇɢʀᴀᴍ URL Uᴘʟᴏᴀᴅᴇʀ Bᴏᴛ.\n\n"
                f"Sᴇɴᴅ ᴍᴇ ᴀ ᴅɪʀᴇᴄᴛ ʟɪɴᴋ ᴀɴᴅ ɪ ᴡɪʟʟ ᴜᴘʟᴏᴀᴅ ɪᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ ᴀs ᴀ ꜰɪʟᴇ/ᴠɪᴅᴇᴏ\n\n"
                f"Usᴇ ʜᴇʟᴘ ʙᴜᴛᴛᴏɴ ᴛᴏ ᴋɴᴏᴡ ʜᴏᴡ ᴛᴏ ᴜsᴇ ᴍᴇ",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                        InlineKeyboardButton("❓ Help", callback_data="help_button")
                    ],
                    [
                        InlineKeyboardButton("📢 Updates", callback_data="updates"),
                        InlineKeyboardButton("🛠️ Support", callback_data="support")
                    ],
                    [InlineKeyboardButton("🍪 Cookie Panel", callback_data="cookie_panel")],
                    [InlineKeyboardButton("ℹ️ About", callback_data="about")]
                ])
            )
        except Exception:
            # If original message was a photo, send a new message
            await callback_query.message.reply(
                f"👋 Hello {callback_query.from_user.mention}!\n\n"
                f"ⵊ Aᴍ Tᴇʟᴇɢʀᴀᴍ URL Uᴘʟᴏᴀᴅᴇʀ Bᴏᴛ.\n\n"
                f"Sᴇɴᴅ ᴍᴇ ᴀ ᴅɪʀᴇᴄᴛ ʟɪɴᴋ ᴀɴᴅ ɪ ᴡɪʟʟ ᴜᴘʟᴏᴀᴅ ɪᴛ ᴛᴏ ᴛᴇʟᴇɢʀᴀᴍ ᴀs ᴀ ꜰɪʟᴇ/ᴠɪᴅᴇᴏ\n\n"
                f"Usᴇ ʜᴇʟᴘ ʙᴜᴛᴛᴏɴ ᴛᴏ ᴋɴᴏᴡ ʜᴏᴡ ᴛᴏ ᴜsᴇ ᴍᴇ",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                        InlineKeyboardButton("❓ Help", callback_data="help_button")
                    ],
                    [
                        InlineKeyboardButton("📢 Updates", callback_data="updates"),
                        InlineKeyboardButton("🛠️ Support", callback_data="support")
                    ],
                    [InlineKeyboardButton("🍪 Cookie Panel", callback_data="cookie_panel")],
                    [InlineKeyboardButton("ℹ️ About", callback_data="about")]
                ])
            )
        return

    # Handle updates button
    elif data == "updates":
        await callback_query.answer("Opening updates channel...")
        try:
            await message.edit(
                "📢 **Stay Updated**\n\n"
                "Join our updates channel to get the latest news and features about the bot:\n\n"
                "🔗 @anujedits76",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join Channel", url="https://t.me/log_ak_bots")],
                    [InlineKeyboardButton("◀️ Back", callback_data="back_to_start")]
                ])
            )
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Updates edit error: {e}")
        return

    elif data == "support":
        await callback_query.answer("Opening support...")
        try:
            await message.edit(
                "🛠️ **Get Support**\n\n"
                "If you need help or want to report an issue, join our support group:\n\n"
                "🔗 @anujeditbyak",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Support Group", url="https://t.me/log_ak_bots")],
                    [InlineKeyboardButton("◀️ Back", callback_data="back_to_start")]
                ])
            )
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Support edit error: {e}")
        return

    elif data == "about":
        await callback_query.answer("Opening about...")
        try:
            await message.edit(
                """ℹ️ **About This Bot**
╭───────────⍟
├📛 Mʏ Nᴀᴍᴇ : URL UPLOADER PRO
├📢 Fʀᴀᴍᴇᴡᴏʀᴋ : PyroBlack 2.7.0
├💮 Lᴀɴɢᴜᴀɢᴇ : Python 3.13.2
├💾 Dᴀᴛᴀʙᴀsᴇ : MongoDB
├🚨 Sᴜᴘᴘᴏʀᴛ Gʀᴏᴜᴘ : JOIN GROUP
├🥏 Cʜᴀɴɴᴇʟ : ANUJ KUMAR
├👨‍💻 Cʀᴇᴀᴛᴇʀ : @anujedits76
╰───────────────⍟
""",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Back", callback_data="back_to_start")]
                ])
            )
        except MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"About edit error: {e}")
        return
    elif data == "show_regular_plans":
        # Regular plans details - calculate prices based on the 1-month price
        text = "**💎 Regular Subscription Plans 💎**\n\n"
        text += "All plans include:\n"
        text += "• Split feature support\n"
        text += "• Custom thumbnail support\n"
        text += "• Custom caption support\n"
        text += "• Screenshots support\n"
        text += "• Sample video support\n\n"
        text += "Select a plan duration:"
        
        keyboard = []
        for duration in DURATION_MULTIPLIERS:
            price = calculate_price(REGULAR_MONTHLY_PRICE, duration)
            duration_name = DURATION_NAMES.get(duration, duration)
            keyboard.append([
                InlineKeyboardButton(f"{duration_name} - ₹{price}", callback_data=f"regular_{duration}")
            ])
        
        keyboard.append([
            InlineKeyboardButton("◀️ Back", callback_data="back_to_main"), 
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_plans")
        ])
        
        try:
            await message.edit(text, reply_markup=InlineKeyboardMarkup(keyboard))
        except MessageNotModified:
            pass
        return
    elif data == "show_student_plans":
        # Student plans details - calculate prices based on the 1-month price
        text = "**🎓 Student Subscription Plans 🎓**\n\n"
        text += "Needs Students Proof to purchase\n\nAll plans include:\n"
        text += "• Split feature support\n"
        text += "• Custom thumbnail support\n"
        text += "• Custom caption support\n"
        text += "• Screenshots support\n"
        text += "• Sample video support\n\n"
        text += "Select a plan duration:"
        
        keyboard = []
        for duration in DURATION_MULTIPLIERS:
            price = calculate_price(STUDENT_MONTHLY_PRICE, duration)
            duration_name = DURATION_NAMES.get(duration, duration)
            keyboard.append([
                InlineKeyboardButton(f"{duration_name} - ₹{price}", callback_data=f"student_{duration}")
            ])
        
        keyboard.append([
            InlineKeyboardButton("◀️ Back", callback_data="back_to_main"), 
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_plans")
        ])
        
        try:
            await message.edit(text, reply_markup=InlineKeyboardMarkup(keyboard))
        except MessageNotModified:
            pass
        return
    elif data == "back_to_main":
        # Return to main plans menu
        text = "**📑 Available Subscription Plans 📑**\n\n"
        text += "Choose from our Regular or Student plans below:"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💎 Regular", callback_data="show_regular_plans"),
                InlineKeyboardButton("🎓 Student", callback_data="show_student_plans")
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_plans")]
        ])
        
        try:
            await message.edit(text, reply_markup=keyboard)
        except MessageNotModified:
            pass
        return
    elif data.startswith(("regular_", "student_")) and not data.endswith("_plans"):
        # Show plan details
        # Use split("_", 1) to correctly handle durations like "1month", "3months", "6months", "1year"
        plan_type, duration = data.split("_", 1)  # "regular" or "student", then full duration key
        
        # Get the base price based on plan type
        base_price = REGULAR_MONTHLY_PRICE if plan_type == "regular" else STUDENT_MONTHLY_PRICE
        price = calculate_price(base_price, duration)
        duration_name = DURATION_NAMES.get(duration, duration)
        
        # Create plan details text
        emoji = "💎" if plan_type == "regular" else "🎓"
        plan_title = "Regular" if plan_type == "regular" else "Student"
        
        text = f"**{emoji} {plan_title} Plan - {duration_name} Subscription {emoji}**\n\n"
        text += f"**Price:** ₹{price}\n"
        text += f"**Duration:** {duration_name}\n\n"
        text += "**Features:**\n"
        text += "• Split feature support\n"
        text += "• Custom thumbnail support\n"
        text += "• Custom caption support\n"
        text += "• Screenshots support\n"
        text += "• Sample video support\n\n"
        
        if plan_type == "student":
            text += "**Note:** Student verification required\n\n"
            
        text += "To purchase this plan, please contact @anujedits76"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Purchase", callback_data=f"purchase_{plan_type}_{duration}")],
            [
                InlineKeyboardButton("◀️ Back", callback_data=f"show_{plan_type}_plans"), 
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_plans")
            ]
        ])
        
        try:
            await message.edit(text, reply_markup=keyboard)
        except MessageNotModified:
            pass
        return
    # Purchase handlers
    elif data.startswith("purchase_"):
        # Handle purchase callbacks
        # data format: "purchase_regular_1month" or "purchase_student_3months"
        # Use split carefully to handle duration keys like "1month", "6months", "1year"
        rest = data[len("purchase_"):]           # "regular_1month"
        plan_type, duration = rest.split("_", 1) # "regular", "1month"
        
        duration_name = DURATION_NAMES.get(duration, duration)
        plan_title = "Regular" if plan_type == "regular" else "Student"
        
        text = f"To complete your purchase of the {plan_title} {duration_name} plan, please contact @NitinSahay.\n\n"
        text += "They will assist you with payment and activation."
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back to Plans", callback_data="back_to_main")],
            [InlineKeyboardButton("❌ Close", callback_data="cancel_plans")]
        ])
        
        try:
            await message.edit(text, reply_markup=keyboard)
        except MessageNotModified:
            pass
        return
        
    elif data == "cancel_plans":
        # Cancel and delete the message
        await callback_query.message.delete()
        await callback_query.answer("Plans Canceled")
        return

    elif data == "close_settings":
        await callback_query.message.delete()
        await callback_query.answer("Settings closed")
        return
    
    # Handle download callbacks
    if data.startswith("dl|"):
        parts = data.split("|")
        if len(parts) != 3:
            await callback_query.answer("Invalid callback data")
            return
        
        _, url_id, format_id = parts
        # format_id may have been truncated to 24 chars during button creation; that's fine
        url_data = await db.get_url(url_id)
        
        if not url_data:
            await callback_query.answer("URL not found in database")
            return
        
        # Get the URL
        url = url_data.get("url")
        
        # Answer the callback query
        await callback_query.answer("Starting download...")
        
        # Update message
        try:
            await message.edit(
                f"⏬ **Downloading...**\n\n"
                f"Please wait, this might take some time.",
            )
        except MessageNotModified:
            pass
        
        # Create a cancel event
        cancel_event = asyncio.Event()
        active_downloads[url_id] = {"event": cancel_event, "user_id": user_id}
        
        # Start download process in background
        def _task_done_cb(task):
            if not task.cancelled() and task.exception():
                logger.error(f"process_download task failed: {task.exception()}")
        task = asyncio.create_task(process_download(client, message, url, url_id, format_id, user_id, cancel_event))
        task.add_done_callback(_task_done_cb)
        return
    
    # Handle cancellation
    if data.startswith("cancel|"):
        url_id = data.split("|")[1]
        try:
            await message.edit("❌ Operation cancelled.")
        except MessageNotModified:
            pass
        await callback_query.answer("Operation cancelled")
        return
    
    if data.startswith("cancel_dl|"):
        url_id = data.split("|")[1]
        
        if url_id in active_downloads:
            active_downloads[url_id]["event"].set()
            await callback_query.answer("Download cancellation requested. Please wait...")
            
            # Update message
            try:
                await message.edit(
                    "⏹️ **Download Cancelled**\n\n"
                    "The download has been cancelled by user."
                )
            except MessageNotModified:
                pass
        else:
            await callback_query.answer("No active download to cancel")
        return
    
    # Handle progress button click
    if data == "progress":
        await callback_query.answer("Download in progress...")
        return

    # Fallthrough: answer any unhandled callback to prevent stuck loading spinner
    try:
        await callback_query.answer()
    except Exception:
        pass

# Helper function to update settings message
async def update_settings_message(client, message, user_id):
    user_data = await db.get_user(user_id)
    if not user_data:
        return
    
    # Get user settings
    upload_mode = user_data.get("upload_mode", DEFAULT_UPLOAD_MODE)
    split_enabled = user_data.get("split_enabled", DEFAULT_SPLIT_SETTING)
    caption_enabled = user_data.get("caption_enabled", False)
    generate_screenshots = user_data.get("generate_screenshots", False)
    generate_sample_video = user_data.get("generate_sample_video", False)
    
    # Create settings markup
    settings_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"Upload as: {'Video' if upload_mode == 'video' else 'File'}", 
                callback_data="toggle_upload_mode"
            )
        ],
        [
            InlineKeyboardButton(
                f"Split files: {'Enabled' if split_enabled else 'Disabled'}", 
                callback_data="toggle_split"
            )
        ],
        [
            InlineKeyboardButton(
                f"Caption: {'Enabled' if caption_enabled else 'Disabled'}", 
                callback_data="toggle_caption"
            )
        ],
        [
            InlineKeyboardButton(
                f"Screenshots: {'Enabled' if generate_screenshots else 'Disabled'}", 
                callback_data="toggle_screenshots"
            )
        ],
        [
            InlineKeyboardButton(
                f"Sample Video: {'Enabled' if generate_sample_video else 'Disabled'}", 
                callback_data="toggle_sample_video"
            )
        ],
        [
            InlineKeyboardButton("◀️ Back", callback_data="back_to_start"),
            InlineKeyboardButton("Close", callback_data="close_settings")
        ]
    ])
    
    try:
        await message.edit(
            "**Bot Settings**\n\n"
            f"Upload Mode: {'Video' if upload_mode == 'video' else 'File'}\n"
            f"Split Files: {'Enabled' if split_enabled else 'Disabled'}\n"
            f"Custom Caption: {'Enabled' if caption_enabled else 'Disabled'}\n"
            f"Generate Screenshots: {'Enabled' if generate_screenshots else 'Disabled'}\n"
            f"Generate Sample Video: {'Enabled' if generate_sample_video else 'Disabled'}",
            reply_markup=settings_markup
        )
    except MessageNotModified:
        pass  # Message content is the same

# Helper function to format duration
def format_duration(seconds):
    if not seconds:
        return "Unknown"
    
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    else:
        return f"{minutes}m {secs}s"


            



def format_size(size_in_bytes):
    """Format size in bytes to human readable format"""
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    elif size_in_bytes < 1024 * 1024:
        return f"{size_in_bytes / 1024:.2f} KB"
    elif size_in_bytes < 1024 * 1024 * 1024:
        return f"{size_in_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_in_bytes / (1024 * 1024 * 1024):.2f} GB"

def format_time(seconds):
    """Format seconds to HH:MM:SS"""
    if not seconds:
        return "00:00"
    
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

async def extract_video_metadata(file_path):
    """Extract video metadata using Hachoir"""
    width = height = None
    duration = 0
    
    def _extract():
        nonlocal width, height, duration
        try:
            parser = createParser(file_path)
            if parser:
                metadata = extractMetadata(parser)
                if metadata:
                    if metadata.has("width"):
                        width = metadata.get("width")
                    if metadata.has("height"):
                        height = metadata.get("height")
                    if metadata.has("duration"):
                        duration = metadata.get("duration").seconds
                parser.close()
        except Exception as e:
            logger.error(f"Error extracting video metadata: {e}")
        return {"width": width, "height": height, "duration": duration}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _extract)

async def upload_file_with_progress(client, message, file_path, chat_id, caption, upload_mode, thumb=None, duration=None, width=None, height=None, _retry=False):
    """Upload file with progress updates"""
    
    # Get file size for progress calculation
    uploaded_size = 0
    start_time = time.time()
    last_update_time = start_time
    
    # Create progress callback
    async def progress_callback(current, total):
        nonlocal uploaded_size, last_update_time
        
        # Calculate progress
        uploaded_size = current
        
        # Guard against division by zero
        if total == 0:
            return
        
        # Only update every 2 seconds to avoid flooding
        current_time = time.time()
        if (current_time - last_update_time) < 2:
            return
            
        last_update_time = current_time
        
        # Calculate speed and ETA
        elapsed_time = current_time - start_time
        if elapsed_time <= 0:
            return
        
        speed = uploaded_size / elapsed_time
        
        # ETA calculation
        remaining_size = total - uploaded_size
        eta = remaining_size / speed if speed > 0 else 0
        
        # Progress percentage
        percentage = (uploaded_size / total) * 100
        
        # Progress bar — 20 blocks for better resolution
        bar_length = 20
        filled_length = int(bar_length * uploaded_size // total)
        progress_bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        try:
            await message.edit(
                f"📤 **Uploading...**\n\n"
                f"**File:** `{os.path.basename(file_path)}`\n\n"
                f"`{progress_bar}`\n"
                f"**Progress:** {percentage:.1f}%  •  {format_size(uploaded_size)} / {format_size(total)}\n"
                f"**Speed:** {format_size(speed)}/s  •  **ETA:** {format_time(eta)}"
            )
        except MessageNotModified:
            pass
    
    try:
        # Upload based on mode
        if upload_mode == "video" and file_path.lower().endswith((".mp4", ".mkv", ".avi", ".webm")):
            video_args = {
                "chat_id": chat_id,
                "video": file_path,
                "caption": caption,
                "supports_streaming": True,
                "progress": progress_callback
            }
            
            # Add optional parameters only if they have valid values
            if duration is not None:
                video_args["duration"] = duration
            if width is not None:
                video_args["width"] = width
            if height is not None:
                video_args["height"] = height
            if thumb:
                video_args["thumb"] = thumb
                
            return await client.send_video(**video_args)
        else:
            document_args = {
                "chat_id": chat_id,
                "document": file_path,
                "caption": caption,
                "force_document": True,
                "progress": progress_callback
            }
            
            if thumb:
                document_args["thumb"] = thumb
                
            return await client.send_document(**document_args)
    except Exception as e:
        logger.error(f"Upload error: {e}")
        # If thumb causes issues, retry without it — but only once
        if "thumb" in str(e).lower() and not _retry:
            logger.info("Retrying upload without thumbnail...")
            return await upload_file_with_progress(
                client, message, file_path, chat_id,
                caption + "\n\n(Uploaded without thumbnail due to error)",
                upload_mode, None, duration, width, height, _retry=True
            )
        raise


    
async def process_download(client, message, url, url_id, format_id, user_id, cancel_event):
    try:
        user_data = await db.get_user(user_id)
        if not user_data:
            try:
                await message.edit("❌ User data not found.")
            except MessageNotModified:
                pass
            return
        
        # Update URL status
        await db.update_url_status(url_id, "downloading")
        
        try:
            global_cookies = await db.get_global_cookies()
            # Retrieve cancel_event from active_downloads dict
            entry = active_downloads.get(url_id, {})
            cancel_event_ref = entry.get("event", cancel_event)

            # Animated status updater during download
            download_done = asyncio.Event()
            async def _animate_download_status():
                dots = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                i = 0
                while not download_done.is_set() and not cancel_event_ref.is_set():
                    filled = i % 10
                    bar = '█' * filled + '░' * (10 - filled)
                    try:
                        await message.edit(
                            f"{dots[i % len(dots)]} **Downloading...**\n\n"
                            f"Please wait, fetching video from server.\n"
                            f"`[{bar}]`"
                        )
                    except MessageNotModified:
                        pass
                    except Exception:
                        pass
                    await asyncio.sleep(2)
                    i += 1

            status_task = asyncio.create_task(_animate_download_status())

            try:
                download_result = await yt_helper.download_video(
                    url=url,
                    format_id=format_id,
                    cancel_event=cancel_event_ref,
                    cookies_content=global_cookies
                )
            finally:
                download_done.set()
                status_task.cancel()
                try:
                    await status_task
                except asyncio.CancelledError:
                    pass
            if cancel_event_ref.is_set():
                try:
                    await message.edit("✖️ Download cancelled by user")
                except MessageNotModified:
                    pass
                return
                
            if not download_result["success"]:
                try:
                    await message.edit(f"❌ Download failed: {download_result.get('error', 'Unknown error')}")
                except MessageNotModified:
                    pass
                return
            
            file_path = download_result["file_path"]
            title = download_result["title"]
            
            # Verify file actually exists on disk
            if not file_path or not os.path.exists(file_path):
                try:
                    await message.edit("❌ Downloaded file not found on disk. Please try again.")
                except MessageNotModified:
                    pass
                await db.update_url_status(url_id, "failed")
                return
            
            # Update message to show processing
            try:
                await message.edit(
                    f"✅ **Download Complete!**\n\n"
                    f"**Title:** {title}\n"
                    f"📤 Processing upload..."
                )
            except MessageNotModified:
                pass
                        
            # Get user preferences
            upload_mode = user_data.get("upload_mode", DEFAULT_UPLOAD_MODE)
            split_enabled = user_data.get("split_enabled", DEFAULT_SPLIT_SETTING)
            caption_enabled = user_data.get("caption_enabled", False)
            custom_caption = user_data.get("caption") if caption_enabled else None
            custom_thumbnail_file_id = user_data.get("thumbnail")
            generate_screenshots = user_data.get("generate_screenshots", False)
            generate_sample_video = user_data.get("generate_sample_video", False)
            
            # Check if file needs to be split
            file_size = os.path.getsize(file_path)
            file_paths = [file_path]
            
            # Extract original file metadata
            original_metadata = {"width": None, "height": None, "duration": 0}
            
            if upload_mode == "video" and file_path.lower().endswith((".mp4", ".mkv", ".avi", ".webm")):
                original_metadata = await extract_video_metadata(file_path)
            
            # Dictionary to store metadata for each part
            part_metadata = {}
            
            if file_size > MAX_FILE_SIZE and split_enabled:
                try:
                    await message.edit(
                        f"📦 **Splitting file...**\n\n"
                        f"File size: {format_size(file_size)} exceeds Telegram limit.\n"
                        f"Splitting into smaller parts."
                    )
                except MessageNotModified:
                    pass
                
                file_paths = await yt_helper.split_file(file_path)
                
                # Calculate metadata for each part if we're dealing with video
                if upload_mode == "video" and original_metadata["duration"] > 0:
                    for i, part_path in enumerate(file_paths):
                        part_size = os.path.getsize(part_path)
                        
                        # First try to get accurate metadata
                        part_meta = await extract_video_metadata(part_path)
                        
                        # If we couldn't get accurate duration, estimate based on size proportion
                        if part_meta["duration"] == 0:
                            # Proportion of file size to estimate duration
                            size_ratio = part_size / file_size
                            estimated_duration = int(original_metadata["duration"] * size_ratio)
                            part_meta["duration"] = estimated_duration
                        
                        # Store metadata
                        part_metadata[part_path] = {
                            "duration": part_meta["duration"],
                            "width": part_meta["width"] or original_metadata["width"],
                            "height": part_meta["height"] or original_metadata["height"],
                            "size": part_size
                        }
            
            # Prepare base caption (Telegram limit: 1024 chars)
            caption = f"**{title[:200]}**"  # truncate title if extremely long
            if custom_caption:
                caption = f"{caption}\n\n{custom_caption}"
            caption = caption[:1024]  # hard cap at Telegram limit
            
            # Upload files
            uploaded_files = []
            generated_thumbnails = []
            
            # Download custom thumbnail if available
            custom_thumbnail_path = None
            if custom_thumbnail_file_id:
                try:
                    await message.edit(
                        f"📤 **Preparing Upload...**\n\n"
                        f"Downloading custom thumbnail..."
                    )
                    # Create a temporary file for the thumbnail
                    thumb_dir = os.path.join(os.getcwd(), "downloads", "thumbnails")
                    os.makedirs(thumb_dir, exist_ok=True)
                    custom_thumbnail_path = os.path.join(thumb_dir, f"thumb_{user_id}_{int(time.time())}.jpg")
                    
                    # Download the thumbnail using file_id
                    await client.download_media(custom_thumbnail_file_id, custom_thumbnail_path)
                    
                    # Add to generated_thumbnails for later cleanup
                    if os.path.exists(custom_thumbnail_path):
                        generated_thumbnails.append(custom_thumbnail_path)
                except Exception as e:
                    logger.error(f"Failed to download custom thumbnail: {e}")
                    custom_thumbnail_path = None
            
            for i, part_path in enumerate(file_paths):
                # Get correct metadata for this part
                width = original_metadata["width"]
                height = original_metadata["height"]
                duration = original_metadata["duration"]
                part_size = os.path.getsize(part_path)
                
                # If this is a split part, use its specific metadata
                if part_path in part_metadata:
                    width = part_metadata[part_path]["width"]
                    height = part_metadata[part_path]["height"]
                    duration = part_metadata[part_path]["duration"]
                    part_size = part_metadata[part_path]["size"]
                
                # Create part-specific caption
                part_caption = caption
                if len(file_paths) > 1:
                    part_duration_str = format_time(duration) if duration else "Unknown"
                    part_size_str = format_size(part_size)
                    part_caption = f"{caption}\n\n" \
                                  f"Part {i+1}/{len(file_paths)}\n" \
                                  f"Duration: {part_duration_str}\n" \
                                  f"Size: {part_size_str}"
                
                # Determine which thumbnail to use
                current_thumbnail = None
                
                if custom_thumbnail_path and os.path.exists(custom_thumbnail_path):
                    # Use downloaded custom thumbnail if available
                    current_thumbnail = custom_thumbnail_path
                    try:
                        await message.edit(
                            f"📤 **Starting Upload...**\n\n"
                            f"File: {os.path.basename(part_path)}\n"
                            f"Part: {i+1}/{len(file_paths)}\n"
                            f"Size: {format_size(part_size)}\n"
                            f"Using custom thumbnail"
                        )
                    except MessageNotModified:
                        pass
                else:
                    # Generate unique thumbnail for each part
                    try:
                        await message.edit(
                            f"📤 **Preparing Upload...**\n\n"
                            f"File: {os.path.basename(part_path)}\n"
                            f"Part: {i+1}/{len(file_paths)}\n"
                            f"Size: {format_size(part_size)}\n"
                            f"Generating unique thumbnail..."
                        )
                    except MessageNotModified:
                        pass
                    
                    if upload_mode == "video":
                        try:
                            # Generate thumbnail from this specific part
                            current_thumbnail = await yt_helper.generate_thumbnail(part_path)
                            if current_thumbnail and os.path.exists(current_thumbnail):
                                generated_thumbnails.append(current_thumbnail)
                            else:
                                logger.warning(f"Failed to generate thumbnail for part {i+1}, proceeding without it")
                        except Exception as e:
                            logger.error(f"Error generating thumbnail for part {i+1}: {e}")
                
                # Update status to uploading
                try:
                    await message.edit(
                        f"📤 **Starting Upload...**\n\n"
                        f"File: {os.path.basename(part_path)}\n"
                        f"Part: {i+1}/{len(file_paths)}\n"
                        f"Size: {format_size(part_size)}"
                    )
                except MessageNotModified:
                    pass
                
                # Upload with progress using the current thumbnail
                try:
                    sent_message = await upload_file_with_progress(
                        client=client,
                        message=message,
                        file_path=part_path,
                        chat_id=user_id,
                        caption=part_caption,
                        upload_mode=upload_mode,
                        thumb=current_thumbnail,
                        duration=duration,
                        width=width,
                        height=height
                    )
                    
                    uploaded_files.append(sent_message.id)
                    
                except Exception as e:
                    logger.error(f"Error uploading file: {e}")
                    await client.send_message(
                        chat_id=user_id,
                        text=f"❌ Error uploading part {i+1}: {str(e)}"
                    )
            
            # Generate and send screenshots if enabled
            screenshots = []
            if generate_screenshots and upload_mode == "video":
                try:
                    await message.edit("🖼️ **Generating screenshots...**")
                except MessageNotModified:
                    pass
                
                screenshots = await yt_helper.generate_screenshots(file_path) or []
                
                if screenshots:
                    # Send screenshots as a media group
                    media_group = []
                    for i, ss_path in enumerate(screenshots[:10]):  # Limit to 10 (Telegram media group limit)
                        if os.path.exists(ss_path):
                            media_group.append(
                                types.InputMediaPhoto(
                                    media=ss_path,
                                    caption=f"Screenshot {i+1}" if i == 0 else ""
                                )
                            )
                    
                    if media_group:
                        await client.send_media_group(user_id, media_group)
            
            # Generate and send sample video if enabled
            sample_path = None
            if generate_sample_video and upload_mode == "video":
                try:
                    await message.edit("🎬 **Generating sample video...**")
                except MessageNotModified:
                    pass
                
                sample_path = await yt_helper.generate_sample_video(file_path)
                
                if sample_path and os.path.exists(sample_path):
                    # Get sample video metadata
                    sample_metadata = await extract_video_metadata(sample_path)
                    
                    # If we couldn't extract sample metadata, use defaults with original dimensions
                    if sample_metadata["duration"] == 0:
                        sample_metadata["duration"] = 20  # Default sample duration
                    if not sample_metadata["width"]:
                        sample_metadata["width"] = original_metadata["width"]
                    if not sample_metadata["height"]:
                        sample_metadata["height"] = original_metadata["height"]
                    
                    # Determine which thumbnail to use for sample video
                    sample_thumbnail = None
                    if custom_thumbnail_path and os.path.exists(custom_thumbnail_path):
                        # Use the custom thumbnail for the sample video as well
                        sample_thumbnail = custom_thumbnail_path
                    else:
                        # Generate a new thumbnail for the sample
                        try:
                            sample_thumbnail = await yt_helper.generate_thumbnail(sample_path)
                            if sample_thumbnail and os.path.exists(sample_thumbnail):
                                generated_thumbnails.append(sample_thumbnail)
                        except Exception as e:
                            logger.error(f"Error generating thumbnail for sample video: {e}")
                    
                    await upload_file_with_progress(
                        client=client,
                        message=message,
                        file_path=sample_path,
                        chat_id=user_id,
                        caption=f"📽️ **Sample video of:** {title}",
                        upload_mode="video",
                        thumb=sample_thumbnail,
                        duration=sample_metadata["duration"],
                        width=sample_metadata["width"],
                        height=sample_metadata["height"]
                    )
            
            # Final completion message
            total_size_str = format_size(sum(os.path.getsize(path) for path in file_paths))
            total_duration_str = format_time(original_metadata["duration"]) if original_metadata["duration"] else "Unknown"
            
            try:
                await message.edit(
                    f"✅ **Download and upload completed!**\n\n"
                    f"**Title:** {title}\n"
                    f"**Format:** {format_id}\n"
                    f"**Total Size:** {total_size_str}\n"
                    f"**Duration:** {total_duration_str}\n"
                    f"**Parts:** {len(file_paths)}"
                )
            except MessageNotModified:
                pass
            
            # Update URL status
            await db.update_url_status(url_id, "completed")
            
            # Clean up files
            cleanup_files = []
            if file_path and os.path.exists(file_path):
                cleanup_files.append(file_path)
            for part_path in file_paths:
                if part_path != file_path and os.path.exists(part_path):
                    cleanup_files.append(part_path)
            if generated_thumbnails:
                for thumb in generated_thumbnails:
                    if os.path.exists(thumb):
                        cleanup_files.append(thumb)
            if screenshots:
                for ss in screenshots:
                    if os.path.exists(ss):
                        cleanup_files.append(ss)
            if sample_path and os.path.exists(sample_path):
                cleanup_files.append(sample_path)
            
            # Cleanup
            yt_helper.cleanup_files(cleanup_files)
        
        except Exception as e:
            logger.error(f"Error in process_download: {e}")
            try:
                await message.edit(f"❌ An error occurred: {str(e)}")
            except MessageNotModified:
                pass
            
            # Update URL status
            await db.update_url_status(url_id, "failed")
        
        finally:
            # Clean up
            if url_id in active_downloads:
                del active_downloads[url_id]

    except Exception as e:
        logger.error(f"Unexpected error in process_download: {e}")
        if url_id in active_downloads:
            del active_downloads[url_id]
        try:
            await db.update_url_status(url_id, "failed")
        except Exception:
            pass

# Main function
async def main():
    await app.start()
    logger.info("Bot started")
    
    try:
        # Keep the bot running
        await idle()
    finally:
        await app.stop()
        try:
            if asyncio.iscoroutinefunction(db.close):
                await db.close()
            else:
                db.close()
        except Exception as e:
            logger.error(f"Error closing database: {e}")
        logger.info("Bot stopped")

if __name__ == "__main__":
    from bot.keep_alive import keep_alive

    keep_alive()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
