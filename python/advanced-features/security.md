# Security

For simplicity W&B uses API keys for authorization when accessing the API. You can find your API keys in your [profile](https://app.wandb.ai/profile). Your API key should be stored securely and never checked into version control. In addition to personal API keys, you can add Service Account users to your team.

### Key Rotation

Both personal and service account keys can be rotated or revoked. Simply create a new API Key or Service Account user and reconfigure your scripts to use the new key. Once all processes are reconfigured, you can remove the old API key from your profile or team.

