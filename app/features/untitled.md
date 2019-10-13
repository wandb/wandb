---
description: Receive a Slack notification when one of your runs crashes or fails
---

# Alerts

W&B can post alerts on Slack when training scripts crash or fail.

### Team Level Alerts

To receive alerts whenever runs launched by members of your team crash or fail, you can configure a team level alert. Team level alerts apply to all projects the team owns and will trigger whenever any member of the team has a crashed or failed run.

Team level alerts apply to all projects belonging to the team. In your team settings page under the `Team Slack Integration` section, select the `Connect Slack` button and authorize the channel into which W&B should post alerts. If you need to change the Slack channel into which W&B posts alerts, you can select the `Disconnect Slack` button and then reconnect with Slack using a new channel of your choice. Only team administrators can manage the team's Slack connection.

Once Slack is connected, team administrators can freely enable and disable alerts.

### User Level Alerts

To receive alerts whenever runs you launch crash or fail, you can configure a user level alert. User level alerts apply to all projects, including team projects, and will trigger whenever the user has a crashed or failed run.

In your user settings page under the `Personal Slack Integration` section, select the `Connect Slack` button and authorize the channel into which W&B should post alerts. The `slackbot` channel is a good choice to keep alerts private. If you need to change the Slack channel into which W&B posts alerts, you can select the `Disconnect Slack` button and then reconnect Slack using the new channel of your choice.

Once Slack is connected, you can freely enable and disable alerts.

