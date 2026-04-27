from etl.cleaners.instagram_cleaner import InstagramCleaner
from etl.cleaners.tiktok_cleaner import TikTokCleaner
from etl.cleaners.youtube_cleaner import YouTubeCleaner

CLEANERS = {
    "instagram": InstagramCleaner,
    "tiktok": TikTokCleaner,
    "youtube": YouTubeCleaner,
}
