# YouTube Channel Analyzer

**Analyze any YouTube channel's full video catalog.** Get engagement metrics, posting patterns, and performance data for content research and competitor analysis.

---

## Use Cases

- **Content Research** - See what topics and formats perform best
- **Competitor Analysis** - Monitor competitor channel performance
- **Trend Spotting** - Identify viral videos early
- **Market Research** - Understand viewer preferences by category

---

## Features

- **Full video catalog** - Fetch all videos or limit to most recent
- **Engagement metrics** - Views, likes, comments, engagement rate
- **Performance ranking** - Videos sorted by view count
- **Channel stats** - Subscriber count, total views, video count
- **Posting patterns** - Videos per week analysis
- **Duration data** - Video length in seconds and formatted

---

## Pricing

**$0.05 per scan**

---

## Quick Start

### Input

```json
{
  "channelId": "UC-3IZKseVpdzPSBaWxBxundA",
  "includeChannelStats": true,
  "maxVideos": 100
}
```

### Output

Each video includes:
```json
{
  "rank": 1,
  "videoId": "dQw4w9WgXcQ",
  "videoUrl": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Video Title",
  "viewCount": 1500000,
  "likeCount": 45000,
  "commentCount": 12000,
  "engagementRate": 3.1,
  "publishedAt": "2024-01-10T15:00:00Z",
  "duration": "PT4M30S",
  "durationSeconds": 270,
  "durationFormatted": "04:30"
}
```

Channel summary includes:
```json
{
  "channelId": "UC-3IZKseVpdzPSBaWxBxundA",
  "channelTitle": "Channel Name",
  "subscriberCount": 5000000,
  "videoCount": 250,
  "viewCount": 1500000000,
  "analyzedVideoCount": 100,
  "totalViewsAnalyzed": 50000000,
  "averageEngagementRate": 2.5,
  "videosPerWeek": 2.3
}
```

---

## Input Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channelId` | string | required | YouTube channel ID |
| `includeChannelStats` | boolean | true | Include channel-level statistics |
| `maxVideos` | integer | 100 | Max videos to fetch (most recent first) |

---

## FAQ

**Q: How do I find a channel ID?**
A: Go to the channel's YouTube page. The channel ID is in the URL after "/channel/".

**Q: How accurate is the data?**
A: Uses YouTube's official Data API v3 — the same data available on YouTube Studio.

**Q: What's the engagement rate?**
A: ((likes + comments) / views) × 100
