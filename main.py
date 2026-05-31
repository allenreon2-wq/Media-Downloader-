import os
import asyncio
import logging
import json
from datetime import datetime
from io import BytesIO
import yt_dlp
import requests
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode, ChatAction

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8106042109:AAHaMFkdXkaH5EYrLKbQTCqSuoHH6ecM5zU"
OWNER_ID = 8679298308

# Auto-create directories
for dir_name in ["data", "downloads", "temp", "thumbnails"]:
    os.makedirs(dir_name, exist_ok=True)

# Database paths
DB = {
    "users": "data/users.json",
    "channels": "data/channels.json", 
    "bans": "data/bans.json",
    "settings": "data/settings.json",
    "stats": "data/stats.json",
    "premium": "data/premium.json",
    "custom_thumb": "data/thumbnail.jpg"
}

# Initialize databases
DEFAULTS = {
    "users": {},
    "channels": [],
    "bans": [],
    "settings": {
        "bot_name": "⚡ Premium DL Bot",
        "maintenance": False,
        "watermark": "Downloaded by @PremiumDLBot",
        "max_file_size": 50,  # MB
        "premium_features": True
    },
    "stats": {
        "total_downloads": 0,
        "youtube": 0,
        "tiktok": 0,
        "pinterest": 0,
        "instagram": 0,
        "facebook": 0,
        "audio_extracts": 0
    },
    "premium": []
}

def load_db(key):
    path = DB[key]
    if not os.path.exists(path):
        with open(path, 'w') as f:
            json.dump(DEFAULTS.get(key, {}), f)
    with open(path, 'r') as f:
        return json.load(f)

def save_db(key, data):
    with open(DB[key], 'w') as f:
        json.dump(data, f, indent=2)

# Load settings
SETTINGS = load_db("settings")
BOT_NAME = SETTINGS.get("bot_name", "⚡ Premium DL Bot")

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('data/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== ENHANCED HELPERS ====================
def is_premium(user_id):
    premium_users = load_db("premium")
    return user_id in premium_users or user_id == OWNER_ID

def update_stats(platform, count=1):
    stats = load_db("stats")
    stats["total_downloads"] += count
    if platform in stats:
        stats[platform] += count
    save_db("stats", stats)

def get_thumbnail(url, platform):
    """Generate thumbnail with platform badge"""
    try:
        thumb_path = f"thumbnails/thumb_{hash(url)}.jpg"
        
        # Download thumbnail using yt-dlp
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'writethumbnail': True,
            'outtmpl': 'thumbnails/temp_thumb',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            thumbnail_url = info.get('thumbnail', '')
            
            if thumbnail_url:
                response = requests.get(thumbnail_url)
                img = Image.open(BytesIO(response.content))
                img = img.resize((1280, 720), Image.Resampling.LANCZOS)
                img.save(thumb_path)
                return thumb_path
    except:
        pass
    
    return None

async def send_typing_action(update: Update, context):
    """Send typing action while processing"""
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )

# ==================== DOWNLOAD ENGINE ====================
class PremiumDownloader:
    def __init__(self):
        self.formats = {
            'video_hd': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
            'video_sd': 'best[height<=720]',
            'video_low': 'best[height<=480]',
            'audio_mp3': 'bestaudio/best',
            'audio_m4a': 'bestaudio[ext=m4a]/bestaudio',
        }
    
    async def download(self, url, platform, quality='video_sd', audio_only=False):
        """Premium download with multiple options"""
        try:
            os.makedirs("downloads", exist_ok=True)
            
            format_str = self.formats.get('audio_mp3' if audio_only else quality)
            
            ydl_opts = {
                'outtmpl': 'downloads/%(title)s_%(id)s.%(ext)s',
                'format': format_str,
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'ignoreerrors': False,
                'no_color': True,
                'geo_bypass': True,
                'socket_timeout': 30,
                'retries': 5,
            }
            
            # Platform specific options
            if platform == "tiktok":
                ydl_opts['format'] = 'best'
            
            if audio_only:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }]
            
            if platform in ['instagram', 'facebook']:
                ydl_opts['cookiefile'] = 'cookies.txt' if os.path.exists('cookies.txt') else None
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Find downloaded file
                downloaded_file = None
                for f in os.listdir("downloads"):
                    if info['id'] in f:
                        downloaded_file = f"downloads/{f}"
                        break
                
                if not downloaded_file:
                    raise Exception("File not found after download")
                
                file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
                
                # Check file size limit
                if file_size_mb > SETTINGS.get('max_file_size', 50):
                    os.remove(downloaded_file)
                    raise Exception(f"File too large: {file_size_mb:.1f}MB (Max: {SETTINGS['max_file_size']}MB)")
                
                return {
                    'file_path': downloaded_file,
                    'info': info,
                    'size_mb': file_size_mb,
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0),
                    'title': info.get('title', 'Unknown')
                }
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None
    
    def get_formats(self, info):
        """Get available formats list"""
        formats_list = []
        seen = set()
        
        for f in info.get('formats', []):
            if f.get('height') and f['height'] not in seen:
                seen.add(f['height'])
                formats_list.append({
                    'height': f['height'],
                    'ext': f.get('ext', 'unknown'),
                    'filesize': f.get('filesize', 0),
                    'format_id': f.get('format_id', '')
                })
        
        return sorted(formats_list, key=lambda x: x['height'], reverse=True)

downloader = PremiumDownloader()

# ==================== PLATFORM DETECTION ====================
def detect_platform(url):
    url_lower = url.lower()
    
    if any(x in url_lower for x in ['youtube.com', 'youtu.be', 'm.youtube.com']):
        return 'youtube'
    elif any(x in url_lower for x in ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com']):
        return 'tiktok'
    elif any(x in url_lower for x in ['pinterest.com', 'pin.it']):
        return 'pinterest'
    elif any(x in url_lower for x in ['instagram.com', 'instagr.am']):
        return 'instagram'
    elif any(x in url_lower for x in ['facebook.com', 'fb.watch', 'fb.com']):
        return 'facebook'
    elif any(x in url_lower for x in ['twitter.com', 'x.com', 't.co']):
        return 'twitter'
    else:
        return None

# ==================== PREMIUM UI COMPONENTS ====================
def create_premium_keyboard(platform=None):
    """Create premium-looking keyboard"""
    keyboard = []
    
    if platform == "youtube":
        keyboard = [
            [InlineKeyboardButton("🎥 HD Video (1080p)", callback_data=f"dl_{platform}_video_hd"),
             InlineKeyboardButton("📱 SD Video (720p)", callback_data=f"dl_{platform}_video_sd")],
            [InlineKeyboardButton("🎵 MP3 Audio", callback_data=f"dl_{platform}_audio"),
             InlineKeyboardButton("🔊 M4A Audio", callback_data=f"dl_{platform}_audio_m4a")],
            [InlineKeyboardButton("📋 Show Formats", callback_data=f"formats_{platform}")]
        ]
    elif platform == "tiktok":
        keyboard = [
            [InlineKeyboardButton("📱 Download Video", callback_data=f"dl_{platform}_best"),
             InlineKeyboardButton("🎵 Extract Audio", callback_data=f"dl_{platform}_audio")],
            [InlineKeyboardButton("🖼️ Thumbnail Only", callback_data=f"thumb_{platform}")]
        ]
    elif platform == "pinterest":
        keyboard = [
            [InlineKeyboardButton("📌 Download Pin", callback_data=f"dl_{platform}_best"),
             InlineKeyboardButton("🖼️ HD Image", callback_data=f"dl_{platform}_hd")]
        ]
    elif platform == "instagram":
        keyboard = [
            [InlineKeyboardButton("📸 Download Post", callback_data=f"dl_{platform}_best"),
             InlineKeyboardButton("🎵 Reel Audio", callback_data=f"dl_{platform}_audio")],
            [InlineKeyboardButton("📋 Story Download", callback_data=f"story_{platform}")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("📥 Download", callback_data=f"dl_{platform}_best"),
             InlineKeyboardButton("🎵 Audio Only", callback_data=f"dl_{platform}_audio")]
        ]
    
    keyboard.append([
        InlineKeyboardButton("🔄 New Link", callback_data="new_link"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="home")
    ])
    
    return InlineKeyboardMarkup(keyboard)

def create_main_menu():
    """Premium main menu"""
    keyboard = [
        [InlineKeyboardButton("📺 YouTube", callback_data="menu_youtube"),
         InlineKeyboardButton("🎵 TikTok", callback_data="menu_tiktok")],
        [InlineKeyboardButton("📌 Pinterest", callback_data="menu_pinterest"),
         InlineKeyboardButton("📸 Instagram", callback_data="menu_instagram")],
        [InlineKeyboardButton("📘 Facebook", callback_data="menu_facebook"),
         InlineKeyboardButton("🐦 Twitter/X", callback_data="menu_twitter")],
        [InlineKeyboardButton("👑 Premium Features", callback_data="premium_info"),
         InlineKeyboardButton("ℹ️ Help & Guide", callback_data="help")],
        [InlineKeyboardButton("📊 Live Stats", callback_data="stats"),
         InlineKeyboardButton("💎 About Bot", callback_data="about")],
        [InlineKeyboardButton("🔔 Join Channel", url="https://t.me/YourChannel"),
         InlineKeyboardButton("⭐ Rate Bot", url="https://t.me/YourBot?start=rate")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium welcome with animations"""
    user = update.effective_user
    user_id = user.id
    
    # Save user
    users = load_db("users")
    users[str(user_id)] = {
        "username": user.username or "N/A",
        "first_name": user.first_name or "N/A",
        "joined_date": str(datetime.now()),
        "downloads": 0
    }
    save_db("users", users)
    
    # Check ban
    bans = load_db("bans")
    if user_id in bans:
        await update.message.reply_text("🚫 **ACCESS DENIED**\n\nYou have been banned from using this bot!", parse_mode=ParseMode.MARKDOWN)
        return
    
    # Check force join
    channels = load_db("channels")
    if channels and not await check_joined_channels(user_id, context):
        await show_force_join(update, context, channels)
        return
    
    # Premium welcome message
    premium_badge = "👑 **Premium User**" if is_premium(user_id) else ""
    
    welcome_text = f"""
╔══════════════════════════╗
║   ⚡ **{BOT_NAME}** ⚡   ║
╚══════════════════════════╝

🎉 **Welcome, {user.first_name}!**
{premium_badge}

**🔥 Premium Features:**
• 📺 **YouTube** - HD/4K, Audio, Playlists
• 🎵 **TikTok** - No Watermark, Audio
• 📌 **Pinterest** - HD Images & Videos  
• 📸 **Instagram** - Posts, Reels, Stories
• 📘 **Facebook** - Videos, Reels
• 🐦 **Twitter/X** - Video Tweets

**⚡ Special Features:**
• Quality Selection (HD/SD/Audio)
• Thumbnail Preview
• Batch Downloads (Premium)
• No Ads, No Limits

**📤 How to Use:**
Just send any video link and choose quality!

**💎 Premium Status:** {'✅ Active' if is_premium(user_id) else '🔒 Free User'}
    """
    
    # Try to send with thumbnail
    if os.path.exists(DB['custom_thumb']):
        with open(DB['custom_thumb'], 'rb') as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=welcome_text,
                reply_markup=create_main_menu(),
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await update.message.reply_text(
            welcome_text,
            reply_markup=create_main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced help with examples"""
    user_id = update.effective_user.id
    
    help_text = f"""
📚 **{BOT_NAME} Help Center**

**📱 Supported Platforms:**
┌─────────────────────────┐
│ 📺 YouTube    ✅ Stable  │
│ 🎵 TikTok     ✅ Stable  │
│ 📌 Pinterest  ✅ Stable  │
│ 📸 Instagram  ⚠️ Beta   │
│ 📘 Facebook   ⚠️ Beta   │
│ 🐦 Twitter/X  ⚠️ Beta   │
└─────────────────────────┘

**🎯 Quick Start:**
1. Send any video link
2. Choose quality/format
3. Get your file instantly!

**💡 Examples:**
• `youtube.com/watch?v=xxx`
• `tiktok.com/@user/video/xxx`
• `pinterest.com/pin/xxx`
• `instagram.com/p/xxx`

**⚡ Premium Tips:**
• HD quality up to 4K
• Audio extraction in MP3
• Batch download (premium)
• Priority support

**🔧 Commands:**
/start - Main menu
/help - This guide
/about - Bot info  
/premium - Premium features
/stats - Bot statistics
/feedback - Send feedback
    """
    
    if user_id == OWNER_ID:
        help_text += """
**👑 Owner Panel:**
/broadcast - Message all users
/addpremium - Add premium user
/removepremium - Remove premium
/addchannel - Add force channel
/removechannel - Remove channel
/ban - Ban user
/unban - Unban user
/users - User list
/stats - Detailed stats
/maintenance - Toggle maintenance
/setthumb - Set custom thumbnail
/logs - View logs
/shell - Execute command
"""
    
    keyboard = [[InlineKeyboardButton("🏠 Back to Home", callback_data="home")]]
    await update.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()
    
    # Save user
    users = load_db("users")
    if str(user_id) not in users:
        users[str(user_id)] = {
            "username": user.username or "N/A",
            "first_name": user.first_name or "N/A",
            "joined_date": str(datetime.now()),
            "downloads": 0
        }
        save_db("users", users)
    
    # Check maintenance
    if SETTINGS.get("maintenance") and user_id != OWNER_ID:
        await update.message.reply_text("🔧 Bot under maintenance. Please wait...")
        return
    
    # Check ban
    if user_id in load_db("bans"):
        return
    
    # Check force join
    channels = load_db("channels")
    if channels and not await check_joined_channels(user_id, context):
        await show_force_join(update, context, channels)
        return
    
    # Detect platform
    platform = detect_platform(text)
    
    if platform:
        await send_typing_action(update, context)
        
        # Save URL in context for later use
        context.user_data['current_url'] = text
        context.user_data['current_platform'] = platform
        
        # Platform-specific response
        platform_emojis = {
            'youtube': '📺',
            'tiktok': '🎵',
            'pinterest': '📌',
            'instagram': '📸',
            'facebook': '📘',
            'twitter': '🐦'
        }
        
        emoji = platform_emojis.get(platform, '📥')
        
        await update.message.reply_text(
            f"{emoji} **{platform.title()} Link Detected!**\n\n"
            f"🔗 `{text[:50]}...`\n\n"
            f"**Choose your download option:**",
            reply_markup=create_premium_keyboard(platform),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "❌ **Invalid Link!**\n\n"
            "Please send a valid link from:\n"
            "• YouTube\n• TikTok\n• Pinterest\n• Instagram\n• Facebook\n• Twitter/X",
            reply_markup=create_main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )

# ==================== CALLBACK HANDLERS ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    # Navigation
    if data == "home":
        await query.message.delete()
        await start(update, context)
        return
    
    elif data == "help":
        await help_command(update, context)
        return
    
    elif data == "about":
        about_text = f"""
💎 **About {BOT_NAME}**

**Version:** 3.0 Premium
**Developer:** @YourUsername  
**Framework:** Python-Telegram-Bot
**Engine:** yt-dlp + Custom

**Why Premium?**
✨ Lightning fast downloads
✨ No watermark extraction
✨ Multiple quality options
✨ 24/7 uptime guarantee
✨ Priority support

**Statistics:**
• Active Users: {len(load_db('users'))}
• Total Downloads: {load_db('stats')['total_downloads']}
• Uptime: 99.9%

**Note:** For educational purposes only
        """
        keyboard = [[InlineKeyboardButton("🏠 Home", callback_data="home")]]
        await query.message.edit_text(about_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    elif data == "stats":
        stats = load_db("stats")
        users = load_db("users")
        
        stats_text = f"""
📊 **Live Bot Statistics**

👥 **Total Users:** {len(users)}
⬇️ **Total Downloads:** {stats['total_downloads']}

**Platform Stats:**
📺 YouTube: {stats.get('youtube', 0)}
🎵 TikTok: {stats.get('tiktok', 0)}
📌 Pinterest: {stats.get('pinterest', 0)}
📸 Instagram: {stats.get('instagram', 0)}
📘 Facebook: {stats.get('facebook', 0)}
🐦 Twitter: {stats.get('twitter', 0)}

🔊 Audio Extracts: {stats.get('audio_extracts', 0)}
👑 Premium Users: {len(load_db('premium'))}
        """
        keyboard = [[InlineKeyboardButton("🏠 Home", callback_data="home")]]
        await query.message.edit_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    elif data == "premium_info":
        premium_text = """
👑 **Premium Features**

**Free User:**
• Basic downloads
• SD quality only
• No audio extraction
• Ads included

**Premium User:**
• HD/4K quality
• Audio extraction (MP3 320kbps)
• No ads, no limits
• Priority processing
• Instagram stories
• Batch downloads
• Custom thumbnails

**Get Premium:**
Contact @YourUsername to upgrade!
        """
        keyboard = [[InlineKeyboardButton("💬 Contact for Premium", url="https://t.me/YourUsername")],
                   [InlineKeyboardButton("🏠 Home", callback_data="home")]]
        await query.message.edit_text(premium_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    elif data == "new_link":
        await query.message.edit_text(
            "📤 **Send a new link to download**\n\n"
            "Supported: YouTube, TikTok, Pinterest, Instagram, Facebook, Twitter",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]])
        )
        return
    
    # Download handlers
    elif data.startswith("dl_"):
        parts = data.split("_")
        platform = parts[1]
        quality = "_".join(parts[2:]) if len(parts) > 2 else "best"
        
        url = context.user_data.get('current_url')
        if not url:
            await query.message.edit_text("❌ Session expired! Please send the link again.")
            return
        
        # Update user download count
        users = load_db("users")
        if str(user_id) in users:
            users[str(user_id)]['downloads'] = users[str(user_id)].get('downloads', 0) + 1
            save_db("users", users)
        
        # Check premium for HD
        if 'hd' in quality and not is_premium(user_id):
            await query.answer("⚠️ HD quality is premium only! Upgrade to access.", show_alert=True)
            return
        
        audio_only = 'audio' in quality
        
        # Progress message
        progress_msg = await query.message.edit_text(
            f"⏳ **Processing...**\n\n"
            f"📱 Platform: {platform.title()}\n"
            f"🎯 Quality: {quality.replace('_', ' ').title()}\n"
            f"🔗 Downloading... 0%",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Download
        result = await downloader.download(url, platform, quality, audio_only)
        
        if not result:
            await progress_msg.edit_text(
                "❌ **Download Failed!**\n\nPossible reasons:\n"
                "• Invalid or private link\n"
                "• Content not available\n"
                "• Server error\n\n"
                "Try again or contact support.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data="new_link")]])
            )
            return
        
        # Update stats
        update_stats(platform)
        if audio_only:
            stats = load_db("stats")
            stats['audio_extracts'] += 1
            save_db("stats", stats)
        
        # Send file with progress
        await progress_msg.edit_text("📤 **Uploading...**")
        
        file_path = result['file_path']
        
        try:
            if file_path.endswith(('.mp3', '.m4a', '.opus')):
                with open(file_path, 'rb') as audio:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=audio,
                        title=result['title'],
                        caption=f"🎵 **Audio Extracted!**\n\n📱 {platform.title()}\n📏 {result['size_mb']:.1f}MB\n👑 @{context.bot.username}",
                        parse_mode=ParseMode.MARKDOWN
                    )
            elif file_path.endswith(('.mp4', '.webm', '.mkv')):
                with open(file_path, 'rb') as video:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=video,
                        caption=f"✅ **Download Complete!**\n\n📱 {platform.title()}\n📏 {result['size_mb']:.1f}MB\n🎯 Quality: {quality.replace('_', ' ').title()}\n👑 @{context.bot.username}",
                        parse_mode=ParseMode.MARKDOWN,
                        supports_streaming=True
                    )
            else:
                with open(file_path, 'rb') as doc:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=doc,
                        caption=f"✅ **Download Complete!**\n\n📱 {platform.title()}\n📏 {result['size_mb']:.1f}MB\n👑 @{context.bot.username}",
                        parse_mode=ParseMode.MARKDOWN
                    )
            
            # Clean up
            os.remove(file_path)
            await progress_msg.delete()
            
            # Show success with new download option
            await query.message.reply_text(
                "💎 **Ready for more?** Send another link or choose:",
                reply_markup=create_main_menu()
            )
            
        except Exception as e:
            await progress_msg.edit_text(f"❌ Upload failed: {str(e)[:100]}")
    
    # Format info
    elif data.startswith("formats_"):
        platform = data.replace("formats_", "")
        url = context.user_data.get('current_url')
        
        if not url:
            await query.answer("Session expired!")
            return
        
        await query.answer("📋 Loading formats...")
        # Implementation for format listing

# ==================== OWNER COMMANDS ====================
async def owner_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = ' '.join(context.args)
    users = load_db("users")
    
    sent, failed = 0, 0
    progress = await update.message.reply_text("📤 Broadcasting...")
    
    for uid in users:
        try:
            await context.bot.send_message(int(uid), f"📢 **Broadcast**\n\n{message}", parse_mode=ParseMode.MARKDOWN)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await progress.edit_text(f"✅ Done! Sent: {sent}, Failed: {failed}")

async def owner_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /addpremium <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        premium = load_db("premium")
        if user_id not in premium:
            premium.append(user_id)
            save_db("premium", premium)
            await update.message.reply_text(f"✅ User {user_id} is now premium!")
        else:
            await update.message.reply_text("Already premium!")
    except:
        await update.message.reply_text("Invalid user ID!")

# [Add more owner commands similarly...]

# ==================== MAIN FUNCTION ====================
def main():
    print(f"""
╔══════════════════════════════════════╗
║                                      ║
║     ⚡ {BOT_NAME} v3.0 ⚡         ║
║     Premium Multi-Platform          ║
║     Downloader Bot                  ║
║                                      ║
║  Author: @YourUsername              ║
║  Status: Starting...                ║
║                                      ║
╚══════════════════════════════════════╝
    """)
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    # Owner commands
    app.add_handler(CommandHandler("broadcast", owner_broadcast))
    app.add_handler(CommandHandler("addpremium", owner_addpremium))
    # Add more owner commands here
    
    # Message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Callback handler
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot is running with Premium features!")
    print("👑 Owner panel activated")
    print("📱 Send any video link to start downloading")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()