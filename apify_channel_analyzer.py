import os
import asyncio
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from apify import Actor

YOUTUBE_API_SERVICE_NAME = 'youtube'
YOUTUBE_API_VERSION = 'v3'


def get_youtube_client():
    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY environment variable is required")
    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)


def parse_duration(duration_str):
    import re
    if not duration_str:
        return 0
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration_str)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds
    return 0


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


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}

        # Charge $0.05 for the run
        await Actor.charge(event_name='run-charge')

        channel_input = actor_input.get('channelId', '').strip()
        if not channel_input:
            await Actor.set_status_message("Channel ID or handle is required")
            await Actor.fail()
            return

        include_channel_stats = actor_input.get('includeChannelStats', True)
        max_videos = actor_input.get('maxVideos', 100)

        Actor.log.info(f"Analyzing channel: {channel_input}, maxVideos={max_videos}")

        try:
            youtube = await asyncio.get_running_loop().run_in_executor(
                None, get_youtube_client
            )

            # Step 1: Get channel info and uploads playlist ID
            # Handle can be with or without @, channel ID starts with UC
            if channel_input.startswith('@'):
                handle = channel_input[1:]  # Remove @
                channels_response = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: youtube.channels().list(
                        part='snippet,contentDetails,statistics,topicDetails',
                        forHandle=handle
                    ).execute()
                )
            elif channel_input.startswith('UC'):
                channels_response = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: youtube.channels().list(
                        part='snippet,contentDetails,statistics,topicDetails',
                        id=channel_input
                    ).execute()
                )
            else:
                # Try as handle anyway
                channels_response = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: youtube.channels().list(
                        part='snippet,contentDetails,statistics,topicDetails',
                        forHandle=channel_input.lstrip('@')
                    ).execute()
                )

            channels = channels_response.get('items', [])
            if not channels:
                await Actor.set_status_message(f"Channel not found: {channel_input}")
                await Actor.fail()
                return

            channel = channels[0]
            channel_id = channel['id']
            snippet = channel.get('snippet', {})
            stats = channel.get('statistics', {})
            content_details = channel.get('contentDetails', {})
            topic_details = channel.get('topicDetails', {})
            uploads_playlist_id = content_details.get('relatedPlaylists', {}).get('uploads')

            if not uploads_playlist_id:
                await Actor.set_status_message("Could not find uploads playlist for channel")
                await Actor.fail()
                return

            # Build channel-level data
            channel_data = {
                'channelId': channel_id,
                'channelHandle': f"@{channel_input.lstrip('@')}" if not channel_input.startswith('UC') else None,
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

            # Step 2: Get all videos from uploads playlist
            videos = []
            next_page_token = None

            while len(videos) < max_videos:
                playlist_response = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: youtube.playlistItems().list(
                        part='snippet,contentDetails',
                        playlistId=uploads_playlist_id,
                        maxResults=min(50, max_videos - len(videos)),
                        pageToken=next_page_token
                    ).execute()
                )

                items = playlist_response.get('items', [])
                if not items:
                    break

                video_ids = []
                for item in items:
                    content = item.get('contentDetails', {})
                    video_id = content.get('videoId', '')
                    if video_id:
                        video_ids.append(video_id)

                # Step 3: Batch fetch video statistics
                if video_ids:
                    video_stats_response = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: youtube.videos().list(
                            part='statistics,contentDetails',
                            id=','.join(video_ids)
                        ).execute()
                    )

                    stats_map = {}
                    for v in video_stats_response.get('items', []):
                        vid = v['id']
                        stats_map[vid] = {
                            'statistics': v.get('statistics', {}),
                            'contentDetails': v.get('contentDetails', {})
                        }

                    # Build video records
                    for item in items:
                        snippet = item.get('snippet', {})
                        content = item.get('contentDetails', {})
                        video_id = content.get('videoId', '')

                        if not video_id or video_id not in stats_map:
                            continue

                        video_stats = stats_map[video_id]['statistics']
                        video_content = stats_map[video_id]['contentDetails']

                        view_count = int(video_stats.get('viewCount', 0) or 0)
                        like_count = int(video_stats.get('likeCount', 0) or 0)
                        comment_count = int(video_stats.get('commentCount', 0) or 0)

                        video_data = {
                            'videoId': video_id,
                            'videoUrl': f'https://www.youtube.com/watch?v={video_id}',
                            'title': snippet.get('title', ''),
                            'description': snippet.get('description', ''),
                            'publishedAt': snippet.get('publishedAt', ''),
                            'thumbnailUrl': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                            'viewCount': view_count,
                            'likeCount': like_count,
                            'commentCount': comment_count,
                            'duration': video_content.get('duration', ''),
                            'durationSeconds': parse_duration(video_content.get('duration', '')),
                            'durationFormatted': format_duration(parse_duration(video_content.get('duration', ''))),
                            'engagementRate': calculate_engagement_rate(view_count, like_count, comment_count),
                        }
                        videos.append(video_data)

                next_page_token = playlist_response.get('nextPageToken')
                if not next_page_token:
                    break

            # Sort by view count (most popular first)
            videos.sort(key=lambda x: x.get('viewCount', 0), reverse=True)

            # Add rank
            for i, video in enumerate(videos, 1):
                video['rank'] = i

            # Calculate channel-level stats
            if videos:
                total_views = sum(v.get('viewCount', 0) for v in videos)
                total_likes = sum(v.get('likeCount', 0) for v in videos)
                total_comments = sum(v.get('commentCount', 0) for v in videos)
                avg_engagement = round(sum(v.get('engagementRate', 0) for v in videos) / len(videos), 2)

                # Posting frequency (videos per week since oldest video)
                oldest_video_date = min(datetime.fromisoformat(v['publishedAt'].replace('Z', '+00:00')) for v in videos if v['publishedAt'])
                days_since_oldest = (datetime.utcnow() - oldest_video_date.replace(tzinfo=None)).days
                videos_per_week = round(len(videos) / max(days_since_oldest, 1) * 7, 1)

                channel_data['analyzedVideoCount'] = len(videos)
                channel_data['totalViewsAnalyzed'] = total_views
                channel_data['totalLikesAnalyzed'] = total_likes
                channel_data['totalCommentsAnalyzed'] = total_comments
                channel_data['averageEngagementRate'] = avg_engagement
                channel_data['videosPerWeek'] = videos_per_week
                channel_data['analysisDate'] = datetime.utcnow().isoformat() + 'Z'

            # Prepare final output
            output = {
                'channel': channel_data if include_channel_stats else {'channelId': channel_id},
                'videos': videos,
                'summary': {
                    'totalVideosAnalyzed': len(videos),
                    'topVideo': videos[0] if videos else None,
                    'averageViews': round(sum(v.get('viewCount', 0) for v in videos) / max(len(videos), 1)),
                    'averageEngagementRate': avg_engagement if videos else 0
                }
            }

            await Actor.push_data({'type': 'channel', **channel_data})
            await Actor.push_data(videos)
            await Actor.set_value('OUTPUT', output)
            Actor.log.info(f"Success! Analyzed {len(videos)} videos from {channel_data.get('channelTitle', channel_id)}")

        except HttpError as e:
            if 'quotaExceeded' in str(e).lower():
                await Actor.set_status_message("YouTube API quota exceeded")
                await Actor.fail()
                return
            raise Exception(f"YouTube API error: {str(e)}")
        except ValueError as e:
            await Actor.set_status_message(str(e))
            await Actor.fail()
            return


if __name__ == '__main__':
    import sys
    is_apify = os.environ.get('APIFY_IS_AT_HOME') or os.environ.get('APIFY_TOKEN')

    if not is_apify and len(sys.argv) > 1:
        channel_id = sys.argv[1]
        os.environ['YOUTUBE_API_KEY'] = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('YOUTUBE_API_KEY')

        print(f"Analyzing channel: {channel_id}")

        from googleapiclient.discovery import build
        youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=os.environ.get('YOUTUBE_API_KEY'))

        channels_response = youtube.channels().list(
            part='snippet,contentDetails,statistics',
            id=channel_id
        ).execute()

        for channel in channels_response.get('items', []):
            snippet = channel.get('snippet', {})
            stats = channel.get('statistics', {})
            print(f"\nChannel: {snippet.get('title', '')}")
            print(f"Subscribers: {int(stats.get('subscriberCount', 0) or 0):,}")
            print(f"Videos: {int(stats.get('videoCount', 0) or 0):,}")
            print(f"Views: {int(stats.get('viewCount', 0) or 0):,}")
    else:
        asyncio.run(main())
