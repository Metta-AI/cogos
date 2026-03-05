# Discord Bot Setup

1. Go to https://discord.com/developers/applications
2. Click 'New Application' and give it a name
3. Go to the 'Bot' tab in the left sidebar
4. Click 'Reset Token' to generate a new bot token
5. Copy the token (you won't be able to see it again)
6. Under 'Privileged Gateway Intents', enable:
   - Message Content Intent
   - Server Members Intent (if needed)
7. Go to 'OAuth2 > URL Generator' to create an invite link
   - Select scopes: bot, applications.commands
   - Select permissions your bot needs
8. Use the generated URL to invite the bot to your server
