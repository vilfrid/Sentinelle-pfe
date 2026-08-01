from etl.cleaners.instagram_cleaner import InstagramCleaner
from etl.cleaners.youtube_cleaner import YouTubeCleaner

CLEANERS = {
    "instagram": InstagramCleaner,
    "youtube":   YouTubeCleaner,
}
