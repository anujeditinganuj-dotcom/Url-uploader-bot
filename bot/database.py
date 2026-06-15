from motor.motor_asyncio import AsyncIOMotorClient
from bot.config import MONGODB_URI, DB_NAME, DEFAULT_UPLOAD_MODE, DEFAULT_SPLIT_SETTING
from bot.config import DEFAULT_CAPTION_ENABLED, DEFAULT_THUMBNAIL_GENERATION, DEFAULT_GENERATE_SCREENSHOTS, DEFAULT_SAMPLE_VIDEO
import datetime
import logging
from datetime import timedelta
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.client = AsyncIOMotorClient(MONGODB_URI)
        self.db = self.client[DB_NAME]
        self.users = self.db["users"]
        self.urls = self.db["urls"]
        self.daily_tasks = self.db["daily_tasks"]
        self.settings = self.db["settings"]
        logger.info("Database connection established")
        
    async def initialize(self):
        await self.create_indexes()

    async def create_indexes(self):
        await self.users.create_index("user_id", unique=True)
        await self.urls.create_index("url_id", unique=True)
        await self.daily_tasks.create_index([(("user_id", 1), ("date", 1))], unique=True)

    async def add_user(self, user_id, username=None):
        user_data = {
            "user_id": user_id,
            "username": username,
            "upload_mode": DEFAULT_UPLOAD_MODE,
            "split_enabled": DEFAULT_SPLIT_SETTING,
            "caption": None,
            "caption_enabled": DEFAULT_CAPTION_ENABLED,
            "thumbnail": None,
            "generate_screenshots": DEFAULT_GENERATE_SCREENSHOTS,
            "generate_sample_video": DEFAULT_SAMPLE_VIDEO,
            "banned": False,
            "is_paid": False,
            "subscription_start": None,
            "paid_expiry": None
        }
        try:
            await self.users.update_one(
                {"user_id": user_id},
                {"$set": user_data},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False

    async def get_user(self, user_id):
        user_data = await self.users.find_one({"user_id": user_id})
        if user_data and user_data.get("is_paid", False) and user_data.get("paid_expiry"):
            # FIX: use utcnow() so comparison matches MongoDB UTC timestamps
            if user_data["paid_expiry"] < datetime.datetime.utcnow():
                await self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_paid": False}}
                )
                user_data["is_paid"] = False
                logger.info(f"User {user_id} paid subscription expired")
        return user_data

    async def update_user_settings(self, user_id, settings):
        try:
            await self.users.update_one({"user_id": user_id}, {"$set": settings})
            return True
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return False

    async def ban_user(self, user_id, banned=True):
        try:
            await self.users.update_one({"user_id": user_id}, {"$set": {"banned": banned}})
            return True
        except Exception as e:
            logger.error(f"Error changing ban status: {e}")
            return False

    async def set_paid_status(self, user_id, is_paid=True, expiry_date=None):
        try:
            update_data = {
                "is_paid": is_paid,
                # FIX: utcnow() so expiry comparison is always in UTC
                "subscription_start": datetime.datetime.utcnow() if is_paid else None
            }
            if expiry_date:
                update_data["paid_expiry"] = expiry_date
            await self.users.update_one({"user_id": user_id}, {"$set": update_data})
            logger.info(f"User {user_id} paid={is_paid} expiry={expiry_date}")
            return True
        except Exception as e:
            logger.error(f"Error setting paid status: {e}")
            return False

    async def get_subscription_details(self, user_id):
        user_data = await self.get_user(user_id)
        if not user_data:
            return None
        subscription = {
            "is_paid": user_data.get("is_paid", False),
            "subscription_start": user_data.get("subscription_start"),
            "expiry_date": user_data.get("paid_expiry"),
            "days_remaining": 0
        }
        if subscription["is_paid"] and subscription["expiry_date"]:
            now = datetime.datetime.utcnow()
            if subscription["expiry_date"] > now:
                subscription["days_remaining"] = (subscription["expiry_date"] - now).days
        return subscription

    async def set_thumbnail(self, user_id, file_id):
        try:
            await self.users.update_one({"user_id": user_id}, {"$set": {"thumbnail": file_id}})
            return True
        except Exception as e:
            logger.error(f"Error setting thumbnail: {e}")
            return False

    async def set_caption(self, user_id, caption):
        try:
            await self.users.update_one({"user_id": user_id}, {"$set": {"caption": caption}})
            return True
        except Exception as e:
            logger.error(f"Error setting caption: {e}")
            return False

    async def delete_caption(self, user_id):
        try:
            await self.users.update_one({"user_id": user_id}, {"$set": {"caption": None, "caption_enabled": False}})
            return True
        except Exception as e:
            logger.error(f"Error deleting caption: {e}")
            return False

    async def get_all_users(self):
        return [user async for user in self.users.find({})]

    async def get_banned_users(self):
        return [user async for user in self.users.find({"banned": True})]

    async def get_paid_users(self):
        now = datetime.datetime.utcnow()
        paid_users = [user async for user in self.users.find({"is_paid": True})]
        valid = []
        for user in paid_users:
            if user.get("paid_expiry") and user["paid_expiry"] < now:
                await self.users.update_one({"user_id": user["user_id"]}, {"$set": {"is_paid": False}})
                logger.info(f"User {user['user_id']} expired")
            else:
                valid.append(user)
        return valid

    async def store_url(self, url_id, url, user_id, status="pending"):
        url_data = {
            "url_id": url_id,
            "url": url,
            "user_id": user_id,
            "status": status,
            "timestamp": datetime.datetime.utcnow()
        }
        try:
            await self.urls.update_one({"url_id": url_id}, {"$set": url_data}, upsert=True)
            return True
        except Exception as e:
            logger.error(f"Error storing URL: {e}")
            return False

    async def update_url_status(self, url_id, status):
        try:
            await self.urls.update_one({"url_id": url_id}, {"$set": {"status": status}})
            return True
        except Exception as e:
            logger.error(f"Error updating URL status: {e}")
            return False

    async def track_daily_task(self, user_id):
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        try:
            result = await self.daily_tasks.update_one(
                {"user_id": user_id, "date": today},
                {"$inc": {"count": 1}},
                upsert=True
            )
            if result.upserted_id:
                return 1
            task_data = await self.daily_tasks.find_one({"user_id": user_id, "date": today})
            return task_data.get("count", 0)
        except Exception as e:
            logger.error(f"Error tracking daily task: {e}")
            return -1

    async def get_daily_task_count(self, user_id):
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        try:
            task_data = await self.daily_tasks.find_one({"user_id": user_id, "date": today})
            return task_data.get("count", 0) if task_data else 0
        except Exception as e:
            logger.error(f"Error getting daily task count: {e}")
            return 0

    async def get_url(self, url_id):
        return await self.urls.find_one({"url_id": url_id})

    # ── Global Admin Cookie Methods ───────────────────────────────────────────
    # Admin sets ONE global cookies.txt → all users' downloads use it

    async def set_global_cookies(self, cookies_content):
        try:
            await self.settings.update_one(
                {"key": "global_cookies"},
                {"$set": {
                    "key": "global_cookies",
                    "value": cookies_content,
                    "updated_at": datetime.datetime.utcnow()
                }},
                upsert=True
            )
            logger.info("Global cookies saved")
            return True
        except Exception as e:
            logger.error(f"Error saving global cookies: {e}")
            return False

    async def get_global_cookies(self):
        try:
            doc = await self.settings.find_one({"key": "global_cookies"})
            return doc.get("value") if doc else None
        except Exception as e:
            logger.error(f"Error getting global cookies: {e}")
            return None

    async def delete_global_cookies(self):
        try:
            await self.settings.delete_one({"key": "global_cookies"})
            logger.info("Global cookies deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting global cookies: {e}")
            return False

    async def close(self):
        self.client.close()
        logger.info("Database connection closed")
