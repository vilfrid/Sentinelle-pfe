from etl.cleaners.instagram_cleaner import InstagramCleaner
from etl.cleaners.tiktok_cleaner import TikTokCleaner
from etl.cleaners.youtube_cleaner import YouTubeCleaner
from etl.cleaners.facebook_cleaner import FacebookCleaner

CLEANERS = {
    "instagram": InstagramCleaner,
    "tiktok": TikTokCleaner,
    "youtube": YouTubeCleaner,
    "facebook": FacebookCleaner,
}
