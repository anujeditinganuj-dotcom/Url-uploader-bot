# Url Uploader Bot

A feature-rich Telegram bot for downloading videos from YouTube and various other platforms using yt-dlp. Built with Pyrogram and MongoDB.

## 🌟 Features

### Core Features
- **Multi-Platform Support**: Download videos from YouTube, Instagram, Facebook, Twitter, and 1000+ sites
- **Format Selection**: Choose from available video formats and resolutions
- **Smart File Splitting**: Automatically splits large files (>1.75GB) to comply with Telegram limits
- **Custom Thumbnails**: Set custom thumbnails for uploaded videos
- **Custom Captions**: Add personalized captions to your downloads
- **Screenshot Generation**: Generate multiple screenshots from downloaded videos
- **Sample Video Creation**: Create 20-second preview clips

### User Management
- **Two-Tier System**: Regular and Student subscription plans
- **Daily Download Limits**: Free users get 20 downloads per day
- **Force Subscribe**: Require users to join channels before using the bot
- **User Database**: Track users, settings, and download history

### Admin Features
- **User Management**: Ban/unban users, add paid subscriptions
- **Subscription Control**: Set custom expiry dates for subscriptions
- **Broadcasting**: Send messages to all users
- **Statistics**: View paid users and their subscription details

## 📋 Prerequisites

- Python 3.11+
- MongoDB database
- FFmpeg installed on system
- Telegram Bot Token
- Telegram API credentials (API_ID and API_HASH)

## 🚀 Installation

### Method 1: Local Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd UrlUploaderCh
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Install FFmpeg**

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

4. **Configure environment variables**

Create a `.env` file in the root directory:
```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
MONGODB_URI=mongodb://localhost:27017
DB_NAME=ytdl_bot_db
ADMINS=your_user_id
PAID_USERS=
FORCE_SUB_CHANNEL1=DSRBotzz
FORCE_SUB_CHANNEL2=PaypalMafiaOfficial
```

5. **Run the bot**
```bash
python3 -m bot
```

### Method 2: Docker Installation

1. **Build the Docker image**
```bash
docker build -t ytdl-bot .
```

2. **Run with Docker**
```bash
docker run -d \
  -e API_ID=your_api_id \
  -e API_HASH=your_api_hash \
  -e BOT_TOKEN=your_bot_token \
  -e MONGODB_URI=your_mongodb_uri \
  -e ADMINS=your_user_id \
  --name ytdl-bot \
  ytdl-bot
```

### Method 3: Docker Compose

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  bot:
    build: .
    container_name: ytdl-bot
    environment:
      - API_ID=${API_ID}
      - API_HASH=${API_HASH}
      - BOT_TOKEN=${BOT_TOKEN}
      - MONGODB_URI=${MONGODB_URI}
      - ADMINS=${ADMINS}
      - FORCE_SUB_CHANNEL1=${FORCE_SUB_CHANNEL1}
      - FORCE_SUB_CHANNEL2=${FORCE_SUB_CHANNEL2}
    restart: unless-stopped
    depends_on:
      - mongodb

  mongodb:
    image: mongo:latest
    container_name: ytdl-mongodb
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
    restart: unless-stopped

volumes:
  mongodb_data:
```

Run with:
```bash
docker-compose up -d
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `API_ID` | Telegram API ID from my.telegram.org | Yes | - |
| `API_HASH` | Telegram API Hash | Yes | - |
| `BOT_TOKEN` | Bot token from @BotFather | Yes | - |
| `MONGODB_URI` | MongoDB connection string | Yes | - |
| `DB_NAME` | Database name | No | `ytdl_bot_db` |
| `ADMINS` | Space-separated admin user IDs | Yes | - |
| `PAID_USERS` | Space-separated paid user IDs | No | - |
| `FORCE_SUB_CHANNEL1` | First required channel username/ID | No | - |
| `FORCE_SUB_CHANNEL2` | Second required channel username/ID | No | - |

### Configuration File (`bot/config.py`)

You can modify default settings in `bot/config.py`:

```python
# Default Settings
DEFAULT_UPLOAD_MODE = "video"  # 'video' or 'file'
DEFAULT_SPLIT_SETTING = True   # Enable file splitting
DEFAULT_FORMAT = "bestvideo+bestaudio"

# File Size Limits (in bytes)
MAX_FILE_SIZE = int(1.75 * (1024 ** 3))  # 1.75GB

# Free users daily download limit
TASKS = 20
```

## 📱 Usage

### User Commands

- `/start` - Start the bot and see main menu
- `/help` - Display help message with all commands
- `/settings` - Configure bot settings
- `/clearthumbnail` - Remove custom thumbnail
- `/caption <text>` - Set custom caption
- `/clearcaption` - Remove custom caption
- `/plans` - View subscription plans
- `/upgrade` - Check subscription status

### Admin Commands

- `/broadcast <message>` - Send message to all users
- `/ban <user_id>` - Ban a user
- `/unban <user_id>` - Unban a user
- `/addpaid <user_id> [duration]` - Add paid subscription
  - Example: `/addpaid 123456789 30d` (30 days)
  - Example: `/addpaid 123456789 3m` (3 months)
  - Example: `/addpaid 123456789 1y` (1 year)
- `/removepaid <user_id>` - Remove paid status
- `/paidusers` - List all paid users

### How to Download

1. Send a video URL to the bot
2. Choose from available formats
3. Wait for download to complete
4. Receive your file(s)

### Supported Platforms

The bot supports 1000+ websites through yt-dlp, including:
- YouTube
- Vimeo
- Dailymotion
- And many more...

## 💎 Subscription Plans

### Regular Plan
- **1 Month**: ₹30
- **3 Months**: ₹85 (~5% discount)
- **6 Months**: ₹160 (~11% discount)
- **1 Year**: ₹300 (~16% discount)

### Student Plan (Requires Verification)
- **1 Month**: ₹10
- **3 Months**: ₹28
- **6 Months**: ₹53
- **1 Year**: ₹100

### Premium Features
- Unlimited downloads (no daily limit)
- File splitting for large videos
- Custom thumbnail support
- Custom caption support
- Screenshot generation
- Sample video creation
- Priority support

## 🗂️ Project Structure

```
UrlUploaderCh/
├── bot/
│   ├── __init__.py
│   ├── __main__.py      # Main bot logic
│   ├── config.py        # Configuration
│   ├── database.py      # Database operations
│   └── yt_helper.py     # Download & processing utilities
├── downloads/           # Temporary download folder
├── .env                 # Environment variables
├── .gitignore
├── Dockerfile
├── docker-compose.yml   # (Optional)
├── requirements.txt
├── README.md
└── LICENSE
```

## 🔧 Troubleshooting

### Common Issues

**Bot doesn't respond:**
- Check if bot token is correct
- Verify MongoDB connection
- Check bot logs for errors

**Downloads fail:**
- Ensure FFmpeg is installed
- Check internet connection
- Verify yt-dlp supports the URL

**File upload errors:**
- Check file size (must be under 2GB for Telegram)
- Enable file splitting in settings
- Verify sufficient disk space

**Thumbnail generation fails:**
- Ensure FFmpeg is properly installed
- Check video file is not corrupted
- Try without custom thumbnail

### Debug Mode

Enable debug logging by modifying `bot/__main__.py`:
```python
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## 📊 Database Schema

### Users Collection
```javascript
{
  user_id: Number,
  username: String,
  upload_mode: String,
  split_enabled: Boolean,
  caption: String,
  caption_enabled: Boolean,
  thumbnail: String,
  generate_screenshots: Boolean,
  generate_sample_video: Boolean,
  banned: Boolean,
  is_paid: Boolean,
  subscription_start: Date,
  paid_expiry: Date
}
```

### URLs Collection
```javascript
{
  url_id: String,
  url: String,
  user_id: Number,
  status: String,
  timestamp: Date
}
```

### Daily Tasks Collection
```javascript
{
  user_id: Number,
  date: String,
  count: Number
}
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the project
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👨‍💻 Author

**Nitin Sahay**
- Telegram: [@NitinSahay](https://t.me/NitinSahay)
- Channel: [@ChronosBots](https://t.me/Aurorabots)

## 🙏 Acknowledgments

- [Pyrogram](https://github.com/pyrogram/pyrogram) - Telegram MTProto API framework
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Video downloader
- [FFmpeg](https://ffmpeg.org/) - Multimedia processing
- [MongoDB](https://www.mongodb.com/) - Database

## ⚠️ Disclaimer

This bot is for educational purposes only. Users are responsible for ensuring they have the right to download and share content. The developers are not responsible for any misuse of this bot.

## 📞 Support

For support, join our Telegram channel [@ChronosBots](https://t.me/ChronosBots) or contact [@NitinSahay](https://t.me/NitinSahay).

## 🔄 Updates

Check [@ChronosBots](https://t.me/ChronosBots) for the latest updates and announcements.

---

Made with ❤️ by ChronosBots
