import os
import re
import sys
import requests
from datetime import datetime, timezone, timedelta
from tower.tower_api_client import AuthenticatedClient
from tower.tower_api_client.api.default import list_runs
from tower.tower_api_client.models.list_runs_status_item import ListRunsStatusItem


def discord_to_slack_markdown(content, mentions=None):
    """Convert Discord markdown to Slack mrkdwn format"""
    if not content:
        return content
    # User mentions: <@userid> -> @username
    if mentions:
        for user in mentions:
            user_id = user.get("id")
            name = user.get("global_name") or user.get("username", user_id)
            content = re.sub(rf"<?@!?{user_id}>?", f"@{name}", content)
    # Links: [text](url) -> <url|text>
    content = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", content)
    # Bold/italic: ***text*** -> *_text_*, **text** -> *text*, *text* -> _text_
    content = re.sub(r"\*{3}(.+?)\*{3}", r"*_\1_*", content)
    content = re.sub(r"\*{2}(.+?)\*{2}", r"*\1*", content)
    content = re.sub(r"\*(.+?)\*", r"_\1_", content)
    # Strikethrough: ~~text~~ -> ~text~
    content = re.sub(r"~~(.+?)~~", r"~\1~", content)
    # Custom emoji: <:name:id> -> :name:
    content = re.sub(r"<a?:([^:]+):\d+>", r":\1:", content)
    return content


def get_tower_api_url():
    """Get Tower API URL, ensuring /v1 suffix is present"""
    tower_api_url = os.getenv("TOWER_URL", "https://api.tower.dev")
    if not tower_api_url.endswith("/v1"):
        tower_api_url = tower_api_url.rstrip("/") + "/v1"
    return tower_api_url


def get_last_successful_run_time(app_name, environment):
    """Get the end time of the last successful run"""
    fallback_mins = 5
    tower_token = os.getenv("TOWER_API_KEY")

    if not tower_token:
        print(f"Warning: TOWER_API_KEY not set, using {fallback_mins}-minute lookback")
        return datetime.now(timezone.utc) - timedelta(minutes=fallback_mins)

    client = AuthenticatedClient(base_url=get_tower_api_url(), token=tower_token)

    try:
        response = list_runs.sync(
            name=app_name,
            client=client,
            page=1,
            page_size=10,
            status=[ListRunsStatusItem.EXITED],
            environment=environment,
        )

        if response and response.runs:
            for run in response.runs:
                if run.ended_at:
                    print(f"Last successful run ended at: {run.ended_at}")
                    return run.ended_at

        print(f"No previous successful runs found, using {fallback_mins}-minute lookback")
        return datetime.now(timezone.utc) - timedelta(minutes=fallback_mins)

    except Exception as e:
        print(f"Warning: Could not fetch last run time: {e}, using {fallback_mins}-minute lookback")
        return datetime.now(timezone.utc) - timedelta(minutes=fallback_mins)


def get_discord_messages(channel_id, token, since=None, limit=100):
    """Fetch recent messages from Discord channel. Returns empty list if channel is inaccessible."""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}
    params = {"limit": limit}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 403:
        print(f"  Warning: No permission to read channel {channel_id}, skipping")
        return []
    if response.status_code == 404:
        print(f"  Warning: Channel {channel_id} not found, skipping")
        return []

    response.raise_for_status()
    messages = response.json()

    if since:
        messages = [
            msg for msg in messages
            if datetime.fromisoformat(msg["timestamp"]) > since
        ]

    return messages


def get_author_name(msg):
    """Extract display name from message."""
    member = msg.get("member", {})
    author = msg.get("author", {})
    return member.get("nick") or author.get("global_name") or author.get("username", "Unknown")


def get_discord_url(msg):
    """Build Discord message URL if possible."""
    if {"guild_id", "channel_id", "id"} <= msg.keys():
        return f"https://discord.com/channels/{msg['guild_id']}/{msg['channel_id']}/{msg['id']}"
    return None


def get_reply_info(msg):
    """Get reply info (name, url) if this is a reply."""
    if msg.get("type") != 19:
        return None, None
    ref = msg.get("referenced_message")
    if not ref:
        return None, None
    author = ref.get("author", {})
    name = author.get("global_name") or author.get("username", "someone")
    ref["guild_id"] = msg["guild_id"]
    url = get_discord_url(ref) if ref.get("id") else None
    return name, url


def message_to_blocks(msg):
    """Convert a Discord message to Slack blocks."""
    content = discord_to_slack_markdown(msg.get("content", ""), msg.get("mentions"))
    if not content:
        return []

    author = get_author_name(msg)
    channel_name = msg.get("_channel_name", "")
    dt = datetime.fromisoformat(msg["timestamp"])

    header = f"[<!date^{dt}^\{time\}>|{timestamp}] *{author}* in #{channel_name}" if channel_name else f"[{timestamp}] *{author}*"

    # Main section with optional View button
    section = {"type": "section", "text": {"type": "mrkdwn", "text": f"{header}:\n{content}"}}
    url = get_discord_url(msg)
    if url:
        section["accessory"] = {"type": "button", "text": {"type": "plain_text", "text": "View in Discord"}, "url": url}

    blocks = [section]

    # Context line for replies (U+FE0E forces text presentation)
    reply_name, reply_url = get_reply_info(msg)
    if reply_name:
        name_link = f"<{reply_url}|*{reply_name}*>" if reply_url else f"*{reply_name}*"
        reply_string = f"reply to {name_link} ↩\uFE0E "

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"{reply_string}\t\t\t\t{dt}"}]
    })

    blocks.append({"type": "divider"})
    return blocks


def post_to_slack(webhook_url, messages):
    """Post messages to Slack channel."""
    if not messages:
        print("No messages to post")
        return

    blocks = []
    for msg in messages:
        blocks.extend(message_to_blocks(msg))

    if blocks:
        response = requests.post(webhook_url, json={"blocks": blocks})
        response.raise_for_status()
        print(f"Posted {len(messages)} messages to Slack")


def get_channel_info(channel_id, token):
    """Fetch channel info from Discord API. Returns (name, guild_id) or (channel_id, None) if inaccessible."""
    url = f"https://discord.com/api/v10/channels/{channel_id}"
    headers = {"Authorization": f"Bot {token}"}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code in (403, 404):
            return channel_id, None
        response.raise_for_status()
        channel = response.json()
        return channel.get("name", channel_id), channel.get("guild_id")
    except Exception:
        return channel_id, None


def main():
    """Mirror Discord messages to Slack"""
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    discord_channel_ids = os.getenv("DISCORD_CHANNEL_IDS", "")
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    environment = os.getenv("TOWER_ENVIRONMENT", "default")

    if not discord_token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set")
        sys.exit(1)
    if not discord_channel_ids:
        print("Error: DISCORD_CHANNEL_IDS environment variable not set")
        sys.exit(1)
    if not slack_webhook_url:
        print("Error: SLACK_WEBHOOK_URL environment variable not set")
        sys.exit(1)

    channel_ids = [cid.strip() for cid in discord_channel_ids.split(",") if cid.strip()]

    if not channel_ids:
        print("Error: No valid channel IDs provided")
        sys.exit(1)

    since = get_last_successful_run_time("discord-mirror", environment)
    print(f"Fetching messages since {since}")

    all_messages = []
    for channel_id in channel_ids:
        channel_name, guild_id = get_channel_info(channel_id, discord_token)
        print(f"Fetching from #{channel_name} ({channel_id})...")
        messages = get_discord_messages(channel_id, discord_token, since=since)
        for msg in messages:
            msg["_channel_name"] = channel_name
            msg["guild_id"] = guild_id
        all_messages.extend(messages)
        print(f"  Found {len(messages)} new messages")

    all_messages.sort(key=lambda m: m.get("timestamp", ""))
    print(f"Total: {len(all_messages)} new messages across {len(channel_ids)} channels")

    if all_messages:
        print("Posting to Slack...")
        post_to_slack(slack_webhook_url, all_messages)
        print("Done!")
    else:
        print("No new messages to post")


if __name__ == "__main__":
    main()
