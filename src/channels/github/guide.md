# GitHub App Setup

1. Go to https://github.com/settings/apps
2. Click 'New GitHub App'
3. Fill in the app name and homepage URL
4. Set permissions the app needs (e.g. Issues, PRs, Contents)
5. Generate a private key and download it
6. Note the App ID from the app settings page
7. Install the app on your organization/repos

The CLI will read App ID and private key from Secrets Manager:

    cogent polis identity keys add github/agent-app-id -v <APP_ID>
    cogent polis identity keys add github/agent-app-private-key -f private-key.pem
