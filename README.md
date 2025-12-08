# Discord Mirror

Mirrors Discord messages to a Slack channel. Designed to run on a schedule via Tower.

The app automatically prevents duplicate messages by checking the Tower API for the last successful run time and only posting messages that appeared after that time.

## Setup

### 1. Create a Discord Bot Token

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application or select an existing one
3. Go to the "Bot" section and create a bot
4. Copy the bot token
5. Enable "Message Content Intent" in the Bot settings
6. Invite the bot to your server with appropriate permissions (Read Messages, Read Message History)

### 2. Get Discord Channel ID

1. Enable Developer Mode in Discord (Settings -> Advanced -> Developer Mode)
2. Right-click on the channel you want to mirror
3. Click "Copy ID"

### 3. Create a Slack Webhook

1. Go to your Slack workspace settings
2. Navigate to Apps -> Incoming Webhooks
3. Create a new webhook for the target channel
4. Copy the webhook URL

### 4. Store Discord Bot Token as a Secret

```bash
tower secrets create --name DISCORD_BOT_TOKEN --value <your-bot-token>
```

### 5. Create a Schedule

Run every 5 minutes:

```bash
tower schedules create \
  --app discord-mirror \
  --cron "*/5 * * * *"
```

## Manual Testing

Test the app manually before scheduling:

```bash
tower run
```

## Configuration

The app uses the following environment variables, you should populate them in your tower secrets:

- `DISCORD_BOT_TOKEN` - Discord bot authentication token
- `DISCORD_CHANNEL_ID` - Discord channel ID to fetch messages from
- `SLACK_WEBHOOK_URL` - Slack webhook URL to post messages to
