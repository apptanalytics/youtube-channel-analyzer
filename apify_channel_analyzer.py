import os
import re
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from apify import Actor

YOUTUBE_API_SERVICE_NAME = 'youtube'
YOUTUBE_API_VERSION = 'v3'

# Tunables
MAX_RETRIES = 4
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
SAFE_MAX_VIDEOS = 500  # quota cap; schema will also reflect this
# YouTube channel IDs are exactly 24 characters: the literal "UC" prefix plus 22
# of [A-Za-z0-9_-]. (The "22" was previously undersized and let the README's
# example "UC-3IZKseVpdzPSBaWxBxundA" fall through to the handle branch.)
HANDLE_RE = re.compile(r'@?[A-Za-z0-9._-]{2,40}')
CHANNEL_ID_RE = re.compile(r'^UC[A-Za-z0-9_-]{22,24}$')
CHANNEL_ID_STRICT_RE = re.compile(r'/channel/(UC[A-Za-z0-9_-]{22,24})')


def get_youtube_client():
    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY environment variable is required")
    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)


def parse_duration(duration_str):
    if not duration_str:
        return 0
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration_str)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def calculate_engagement_rate(view_count, like_count, comment_count):
    if not view_count or view_count == 0:
        return 0
    return round(((like_count or 0) + (comment_count or 0)) / view_count * 100, 2)


def format_duration(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def normalize_channel_input(raw):
    """
    Accepts: UC... channel ID, @handle, bare handle, or any youtube.com URL form.
    Returns (kind, value) where kind in {'id', 'handle'}. Raises ValueError on garbage.
    """
    if raw is None:
        raise ValueError("channelId is required")
    s = str(raw).strip()
    if not s:
        raise ValueError("channelId is required")

    # If it's a URL, try to extract a channel ID or handle from the path.
    if s.startswith('http://') or s.startswith('https://'):
        try:
            u = urlparse(s)
        except Exception:
            raise ValueError(f"Invalid channel URL: {raw!r}")
        host = (u.netloc or '').lower()
        if 'youtube.com' not in host and 'youtu.be' not in host:
            raise ValueError(f"Not a YouTube URL: {raw!r}")
        path = u.path or ''
        # /channel/UCxxxx
        m = re.search(CHANNEL_ID_STRICT_RE, path)
        if m:
            return ('id', m.group(1))
        # /@handle
        m = re.search(r'/@([A-Za-z0-9._-]{2,40})', path)
        if m:
            return ('handle', m.group(1).lower())
        # /user/legacy  (rare, but be tolerant)
        m = re.search(r'/(?:user|c)/([A-Za-z0-9._-]{2,40})', path)
        if m:
            return ('handle', m.group(1).lower())
        # /handle (custom URL)
        m = re.search(r'/(?:c/)?([A-Za-z0-9._-]{3,40})', path)
        if m:
            return ('handle', m.group(1).lower())
        raise ValueError(f"Could not extract a channel identifier from URL: {raw!r}")

    # Bare channel ID
    if CHANNEL_ID_RE.match(s):
        return ('id', s)

    # Strip leading @ if present, then validate handle shape and lowercase
    handle = s[1:] if s.startswith('@') else s
    if not HANDLE_RE.fullmatch('@' + handle):
        raise ValueError(
            f"Invalid channel input: {raw!r}. Expected a channel ID (UC...), a handle (@name), or a YouTube URL."
        )
    # The "UC" prefix is reserved for channel IDs; no real handle starts with it.
    # Catches "UC_tooshort" and other ID-shaped but malformed strings.
    if handle.upper().startswith('UC') and len(handle) != 24:
        raise ValueError(
            f"Looks like a channel ID with the wrong length: {raw!r}. Channel IDs must be 'UC' followed by 22 characters."
        )
    return ('handle', handle.lower())


def _is_retryable(err):
    if isinstance(err, HttpError):
        try:
            return int(err.resp.status) in RETRYABLE_HTTP_CODES
        except Exception:
            return False
    return False


async def call_youtube(executor, fn, *, what):
    """Run a YouTube API call with exponential backoff on retryable errors."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            return await executor.run_in_executor(None, fn)
        except HttpError as e:
            last_err = e
            status = getattr(e.resp, 'status', None)
            if status == 403 and 'quotaExceeded' in str(e):
                # Hard fail — retrying won't help and we don't want to spam.
                raise
            if not _is_retryable(e) or attempt == MAX_RETRIES - 1:
                raise
            backoff = min(2 ** attempt, 8) + (0.1 * attempt)
            Actor.log.warning(f"{what} failed (HTTP {status}); retrying in {backoff:.1f}s")
            await asyncio.sleep(backoff)
        except Exception as e:
            last_err = e
            if attempt == MAX_RETRIES - 1:
                raise
            backoff = min(2 ** attempt, 8) + (0.1 * attempt)
            Actor.log.warning(f"{what} failed ({type(e).__name__}: {e}); retrying in {backoff:.1f}s")
            await asyncio.sleep(backoff)
    # Should be unreachable
    raise last_err  # pragma: no cover


YOUTUBE_VIDEO_CATEGORIES = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "18": "Short Movies",
    "19": "Travel & Events",
    "20": "Gaming",
    "21": "Videoblogging",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
    "30": "Movies",
    "31": "Anime/Animation",
    "32": "Action/Adventure",
    "33": "Classics",
    "34": "Comedy",
    "35": "Documentary",
    "36": "Drama",
    "37": "Family",
    "38": "Foreign",
    "39": "Horror",
    "40": "Sci-Fi/Fantasy",
    "41": "Thriller",
    "42": "Shorts",
    "43": "Shows",
    "44": "Trailers",
}


async def analyze_channel(youtube, channel_input, max_videos, executor):
    """Resolve input, fetch channel + videos, return (channel_data, videos). Raises on error."""
    kind, value = normalize_channel_input(channel_input)

    if kind == 'id':
        channels_response = await call_youtube(
            executor,
            lambda: youtube.channels().list(
                part='snippet,contentDetails,statistics,topicDetails',
                id=value,
            ).execute(),
            what="channels.list (id)",
        )
    else:
        channels_response = await call_youtube(
            executor,
            lambda: youtube.channels().list(
                part='snippet,contentDetails,statistics,topicDetails',
                forHandle=value,
            ).execute(),
            what="channels.list (handle)",
        )

    channels = channels_response.get('items', [])
    if not channels:
        raise ValueError(f"Channel not found: {channel_input}")

    channel = channels[0]
    channel_id = channel['id']
    snippet = channel.get('snippet', {})
    stats = channel.get('statistics', {})
    content_details = channel.get('contentDetails', {})
    topic_details = channel.get('topicDetails', {})
    uploads_playlist_id = content_details.get('relatedPlaylists', {}).get('uploads')

    if not uploads_playlist_id:
        raise ValueError(f"Could not find uploads playlist for channel {channel_id}")

    handle = snippet.get('customUrl', '').lstrip('@') or (value if kind == 'handle' else '')
    channel_data = {
        'channelId': channel_id,
        'channelHandle': f"@{handle}" if handle else None,
        'channelTitle': snippet.get('title', ''),
        'channelDescription': snippet.get('description', ''),
        'customUrl': snippet.get('customUrl', ''),
        'publishedAt': snippet.get('publishedAt', ''),
        'thumbnailUrl': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
        'subscriberCount': int(stats.get('subscriberCount', 0) or 0),
        'videoCount': int(stats.get('videoCount', 0) or 0),
        'viewCount': int(stats.get('viewCount', 0) or 0),
        'topicCategories': topic_details.get('topicCategories', []),
    }

    # Step 2: Walk the uploads playlist.
    videos = []
    next_page_token = None
    while len(videos) < max_videos:
        page_size = min(50, max_videos - len(videos))
        playlist_response = await call_youtube(
            executor,
            lambda ps=page_size, tok=next_page_token: youtube.playlistItems().list(
                part='snippet,contentDetails',
                playlistId=uploads_playlist_id,
                maxResults=ps,
                pageToken=tok,
            ).execute(),
            what="playlistItems.list",
        )

        items = playlist_response.get('items', [])
        if not items:
            break

        video_ids = [
            (item.get('contentDetails') or {}).get('videoId', '')
            for item in items
        ]
        video_ids = [vid for vid in video_ids if vid]

        if video_ids:
            video_stats_response = await call_youtube(
                executor,
                lambda ids=list(video_ids): youtube.videos().list(
                    part='snippet,statistics,contentDetails',
                    id=','.join(ids),
                ).execute(),
                what="videos.list",
            )

            stats_map = {}
            for v in video_stats_response.get('items', []):
                vid = v['id']
                stats_map[vid] = {
                    'snippet': v.get('snippet', {}),
                    'statistics': v.get('statistics', {}),
                    'contentDetails': v.get('contentDetails', {}),
                }

            for item in items:
                ps = item.get('snippet', {})
                content = item.get('contentDetails', {})
                video_id = content.get('videoId', '')
                if not video_id or video_id not in stats_map:
                    continue

                v_stats = stats_map[video_id]['statistics']
                v_content = stats_map[video_id]['contentDetails']
                v_snippet = stats_map[video_id]['snippet']

                view_count = int(v_stats.get('viewCount', 0) or 0)
                like_count = int(v_stats.get('likeCount', 0) or 0)
                comment_count = int(v_stats.get('commentCount', 0) or 0)
                category_id = v_snippet.get('categoryId', '')
                category_name = YOUTUBE_VIDEO_CATEGORIES.get(category_id, 'Unknown')
                duration_iso = v_content.get('duration', '')
                duration_seconds = parse_duration(duration_iso)

                videos.append({
                    'videoId': video_id,
                    'videoUrl': f'https://www.youtube.com/watch?v={video_id}',
                    'title': ps.get('title', ''),
                    'publishedAt': ps.get('publishedAt', ''),
                    'thumbnailUrl': ps.get('thumbnails', {}).get('high', {}).get('url', ''),
                    'categoryId': category_id,
                    'categoryName': category_name,
                    'viewCount': view_count,
                    'likeCount': like_count,
                    'commentCount': comment_count,
                    'duration': duration_iso,
                    'durationSeconds': duration_seconds,
                    'durationFormatted': format_duration(duration_seconds),
                    'engagementRate': calculate_engagement_rate(view_count, like_count, comment_count),
                })

        next_page_token = playlist_response.get('nextPageToken')
        if not next_page_token:
            break

    # Sort by view count, most popular first
    videos.sort(key=lambda x: x.get('viewCount', 0), reverse=True)
    for i, video in enumerate(videos, 1):
        video['rank'] = i

    if videos:
        total_views = sum(v.get('viewCount', 0) for v in videos)
        total_likes = sum(v.get('likeCount', 0) for v in videos)
        total_comments = sum(v.get('commentCount', 0) for v in videos)
        avg_engagement = round(
            sum(v.get('engagementRate', 0) for v in videos) / len(videos), 2
        )

        dated = [
            v for v in videos
            if v.get('publishedAt') and 'T' in v['publishedAt']
        ]
        if dated:
            oldest_video_date = min(
                datetime.fromisoformat(v['publishedAt'].replace('Z', '+00:00'))
                for v in dated
            )
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            days_since_oldest = max((now - oldest_video_date.replace(tzinfo=None)).days, 1)
            videos_per_week = round(len(videos) / days_since_oldest * 7, 1)
        else:
            videos_per_week = 0.0

        channel_data['analyzedVideoCount'] = len(videos)
        channel_data['totalViewsAnalyzed'] = total_views
        channel_data['totalLikesAnalyzed'] = total_likes
        channel_data['totalCommentsAnalyzed'] = total_comments
        channel_data['averageEngagementRate'] = avg_engagement
        channel_data['videosPerWeek'] = videos_per_week
        channel_data['analysisDate'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    return channel_data, videos


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}

        # --- Parse + validate BEFORE any work or charge ---
        raw_channel = (actor_input.get('channelId') or '').strip() if isinstance(actor_input.get('channelId'), str) else actor_input.get('channelId')
        try:
            kind, value = normalize_channel_input(raw_channel)
        except ValueError as e:
            await Actor.set_status_message(str(e))
            await Actor.fail()
            return

        include_channel_stats = bool(actor_input.get('includeChannelStats', True))

        # Clamp maxVideos to a quota-safe range. 1 video minimum, SAFE_MAX_VIDEOS cap.
        try:
            requested = int(actor_input.get('maxVideos', 100))
        except (TypeError, ValueError):
            requested = 100
        max_videos = max(1, min(SAFE_MAX_VIDEOS, requested if requested > 0 else 100))
        if requested > SAFE_MAX_VIDEOS:
            Actor.log.info(
                f"Requested maxVideos={requested} exceeds safe cap; clamping to {SAFE_MAX_VIDEOS}"
            )

        Actor.log.info(
            f"Analyzing channel {kind}={value}, includeChannelStats={include_channel_stats}, maxVideos={max_videos}"
        )

        try:
            youtube = get_youtube_client()
            executor = asyncio.get_running_loop()

            channel_data, videos = await analyze_channel(youtube, raw_channel, max_videos, executor)

            # --- All work succeeded. NOW we charge. ---
            await Actor.charge(event_name='run-charge')

            summary = {
                'totalVideosAnalyzed': len(videos),
                'topVideo': videos[0] if videos else None,
                'averageViews': round(
                    sum(v.get('viewCount', 0) for v in videos) / max(len(videos), 1)
                ) if videos else 0,
                'averageEngagementRate': channel_data.get('averageEngagementRate', 0),
            }

            output = {
                'channel': channel_data if include_channel_stats else {'channelId': channel_data['channelId']},
                'videos': videos,
                'summary': summary,
            }

            await Actor.push_data({'type': 'channel', **channel_data})
            if videos:
                await Actor.push_data(videos)
            await Actor.set_value('OUTPUT', output)
            Actor.log.info(
                f"Success! Analyzed {len(videos)} videos from "
                f"{channel_data.get('channelTitle') or channel_data['channelId']}"
            )

        except HttpError as e:
            status = getattr(e.resp, 'status', None)
            reason = getattr(e.resp, 'reason', '') if hasattr(e, 'resp') else ''
            body = ''
            try:
                body = e.content.decode('utf-8', errors='replace') if getattr(e, 'content', None) else ''
            except Exception:
                pass

            err_kind = 'youtube_api'
            if status == 403 and 'quotaExceeded' in str(e):
                msg = "YouTube Data API daily quota exceeded. Try again tomorrow or rotate the API key."
            elif status == 403 and 'forHandle' in body:
                # YouTube tightened the forHandle endpoint in 2025; some
                # handles now require OAuth. Tell the user the workaround.
                msg = (
                    "YouTube API rejected this handle lookup with HTTP 403. "
                    "Try the channel's UC... ID instead, or sign in with OAuth."
                )
                err_kind = 'handle_403'
            elif status == 404:
                msg = f"YouTube API returned 404 for {kind}={value}. The channel or resource may have been removed."
            elif status in RETRYABLE_HTTP_CODES:
                msg = f"YouTube API transient error (HTTP {status} {reason}) after {MAX_RETRIES} retries: {e}"
                err_kind = 'youtube_transient_exhausted'
            else:
                msg = f"YouTube API error (HTTP {status} {reason}): {e}"
            if body and 'quotaExceeded' not in body:
                msg += f"  body: {body[:300]}"
            Actor.log.error(msg)
            await Actor.set_status_message(msg)
            try:
                await Actor.push_data({
                    'type': 'error',
                    'error': err_kind,
                    'detail': msg,
                    'input': {
                        'raw': raw_channel,
                        'resolved_kind': kind,  # 'id' or 'handle'
                        'resolved_value': value,
                        'maxVideos': max_videos,
                    },
                })
            except Exception:
                pass
            await Actor.fail()
        except ValueError as e:
            Actor.log.error(str(e))
            await Actor.set_status_message(str(e))
            try:
                await Actor.push_data({
                    'type': 'error',
                    'error': 'invalid_input',
                    'detail': str(e),
                    'input': {'raw': raw_channel, 'maxVideos': max_videos},
                })
            except Exception:
                pass
            await Actor.fail()
        except Exception as e:
            msg = f"Unexpected error: {type(e).__name__}: {e}"
            Actor.log.exception(msg)
            await Actor.set_status_message(msg)
            try:
                await Actor.push_data({
                    'type': 'error',
                    'error': 'unexpected',
                    'detail': msg,
                    'input': {'raw': raw_channel, 'maxVideos': max_videos},
                })
            except Exception:
                pass
            await Actor.fail()


if __name__ == '__main__':
    asyncio.run(main())
