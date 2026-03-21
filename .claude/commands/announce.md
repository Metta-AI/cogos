Post a message to Discord #cogents.

## Usage

`/announce <message>`

If no message is provided in $ARGUMENTS, ask the user what to announce.

## Steps

1. Determine the message to post:
   - If `$ARGUMENTS` is non-empty, use it as the message
   - Otherwise, ask the user what they'd like to announce
2. Post to Discord #cogents (channel `1475918657153663018`) using the announce module:
   ```bash
   set -a && source ~/.env && set +a && \
   PYTHONPATH=src uv run python -m cogos.io.discord.announce \
     --channel-id 1475918657153663018 \
     --username "$(basename $(pwd))" \
     --message "$MESSAGE"
   ```
   - Keep the message under 2000 characters
3. Print the message locally so the user can see what was announced
