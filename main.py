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
    """Fetch recent messages from Discord channel"""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}
    params = {"limit": limit}

    response = requests.get(url, headers=headers, params=params)
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
        author = msg.get("author", {}).get("username", "Unknown")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")

        if content:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{author}* ({timestamp}):\n{content}"
                }
            })
            blocks.append({"type": "divider"})

    if blocks:
        payload = {"blocks": blocks}
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        print(f"Posted {len(messages)} messages to Slack")


def main():
    """Mirror Discord messages to Slack"""
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
    slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    environment = os.getenv("TOWER_ENVIRONMENT", "default")

    if not discord_token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set")
        sys.exit(1)
    if not discord_channel_id:
        print("Error: DISCORD_CHANNEL_ID environment variable not set")
        sys.exit(1)
    if not slack_webhook_url:
        print("Error: SLACK_WEBHOOK_URL environment variable not set")
        sys.exit(1)

    since = get_last_successful_run_time("discord-mirror", environment)
    print(f"Fetching messages from Discord channel: {discord_channel_id} since {since}")
    messages = get_discord_messages(discord_channel_id, discord_token, since=since)
    print(f"Found {len(messages)} new messages")

    if messages:
        print(f"Posting to Slack...")
        post_to_slack(slack_webhook_url, messages)
        print("Done!")
    else:
        print("No new messages to post")


if __name__ == "__main__":
    main()
