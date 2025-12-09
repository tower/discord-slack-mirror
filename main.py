import os
import sys
import requests
from datetime import datetime, timezone, timedelta
from tower.tower_api_client import AuthenticatedClient
from tower.tower_api_client.api.default import list_runs
from tower.tower_api_client.models.list_runs_status_item import ListRunsStatusItem


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
            if datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00")) > since
        ]

    return messages


def post_to_slack(webhook_url, messages):
    """Post messages to Slack channel"""
    if not messages:
        print("No messages to post")
        return

    blocks = []
    for msg in reversed(messages):
        author_data = msg.get("author", {})
        member_data = msg.get("member", {})
        author = (
            member_data.get("nick")
            or author_data.get("global_name")
            or author_data.get("username", "Unknown")
        )
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")
        channel_name = msg.get("_channel_name", "")

        if content:
            header = f"*{author}* in #{channel_name}" if channel_name else f"*{author}*"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{header} ({timestamp}):\n{content}"
                }
            })
            blocks.append({"type": "divider"})

    if blocks:
        payload = {"blocks": blocks}
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        print(f"Posted {len(messages)} messages to Slack")


def get_channel_name(channel_id, token):
    """Fetch the channel name from Discord API. Returns channel_id if inaccessible."""
    url = f"https://discord.com/api/v10/channels/{channel_id}"
    headers = {"Authorization": f"Bot {token}"}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code in (403, 404):
            return channel_id
        response.raise_for_status()
        channel = response.json()
        return channel.get("name", channel_id)
    except Exception:
        return channel_id


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
        channel_name = get_channel_name(channel_id, discord_token)
        print(f"Fetching from #{channel_name} ({channel_id})...")
        messages = get_discord_messages(channel_id, discord_token, since=since)
        for msg in messages:
            msg["_channel_name"] = channel_name
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
