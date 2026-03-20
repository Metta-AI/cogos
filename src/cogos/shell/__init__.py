"""CogentShell — interactive Unix-like shell for CogOS."""

from __future__ import annotations

from cogos.db.models import Channel, ChannelMessage, ChannelType

_STDIN_CHANNEL = "io:stdin"
_STDOUT_CHANNEL = "io:stdout"


_STDERR_CHANNEL = "io:stderr"


def _ensure_io_channels(repo) -> tuple[Channel, Channel, Channel]:
    """Create stdin/stdout/stderr channels if they don't exist."""
    channels = []
    for name in (_STDIN_CHANNEL, _STDOUT_CHANNEL, _STDERR_CHANNEL):
        ch = repo.get_channel_by_name(name)
        if not ch:
            ch = Channel(name=name, channel_type=ChannelType.NAMED)
            repo.upsert_channel(ch)
        channels.append(ch)
    return channels[0], channels[1], channels[2]


class CogentShell:
    """Main shell class — instantiated by the CLI entry point."""

    def __init__(self, cogent_name: str, *, bedrock_client=None) -> None:
        self.cogent_name = cogent_name
        self._bedrock_client = bedrock_client

    def run(self) -> None:
        """Start the interactive shell loop."""
        from cogos.db.factory import create_repository
        from cogos.shell.commands import ShellState, build_registry
        from cogos.shell.completer import ShellCompleter
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML

        repo = create_repository()
        state = ShellState(cogent_name=self.cogent_name, repo=repo, cwd="")

        # Set up stdin/stdout/stderr channels
        stdin_ch, stdout_ch, stderr_ch = _ensure_io_channels(repo)
        state.stdin_channel = stdin_ch
        state.stdout_channel = stdout_ch
        state.stderr_channel = stderr_ch
        # Track last-seen messages so we can drain new ones
        stdout_msgs = repo.list_channel_messages(stdout_ch.id, limit=1)
        state.stdout_cursor = stdout_msgs[-1].created_at if stdout_msgs else None
        stderr_msgs = repo.list_channel_messages(stderr_ch.id, limit=1)
        state.stderr_cursor = stderr_msgs[-1].created_at if stderr_msgs else None

        state.bedrock_client = self._bedrock_client

        registry = build_registry()
        completer = ShellCompleter(state, registry)

        # Persistent history backed by CogOS file store
        from cogos.shell.history import CogOSHistory
        history = CogOSHistory(repo)

        def _bottom_toolbar():
            try:
                procs = repo.list_processes()
                running = sum(1 for p in procs if p.status.value == "running")
                waiting = sum(1 for p in procs if p.status.value in ("waiting", "runnable"))
                files = repo.list_files(limit=1000)
                caps = repo.list_capabilities(enabled_only=True)
                return HTML(
                    f" procs: <b>{running}</b> running, <b>{waiting}</b> waiting"
                    f" | files: <b>{len(files)}</b>"
                    f" | caps: <b>{len(caps)}</b> enabled"
                )
            except Exception:
                return ""

        session: PromptSession = PromptSession(
            history=history,
            completer=completer,
            bottom_toolbar=_bottom_toolbar,
            complete_while_typing=False,
            enable_history_search=True,
        )

        def _drain_io():
            """Print any new messages on io:stdout and io:stderr since last check."""
            for ch, cursor_attr, prefix, color in [
                (stdout_ch, "stdout_cursor", "", ""),
                (stderr_ch, "stderr_cursor", "", "\033[31m"),
            ]:
                cursor = getattr(state, cursor_attr)
                msgs = repo.list_channel_messages(ch.id, limit=50, since=cursor)
                for m in msgs:
                    payload = m.payload
                    if isinstance(payload, dict):
                        text = payload.get("text", payload.get("data", ""))
                    else:
                        text = str(payload)
                    if text:
                        if color:
                            print(f"{color}{text}\033[0m")
                        else:
                            print(text)
                    setattr(state, cursor_attr, m.created_at)

        def _publish_stdin(line: str):
            """Publish a user command to io:stdin."""
            repo.append_channel_message(ChannelMessage(
                channel=stdin_ch.id,
                sender_process=None,
                payload={"text": line, "source": "shell"},
            ))

        print(f"CogOS shell for \033[1;36m{self.cogent_name}\033[0m (type 'help' for commands, 'exit' to quit)")

        while True:
            # Drain stdout before prompting (catches async process output)
            _drain_io()

            try:
                cwd_display = "/" + state.cwd.rstrip("/") if state.cwd else "/"
                prompt_text = HTML(
                    f"<b><ansicyan>{self.cogent_name}</ansicyan></b>"
                    f":{cwd_display}$ "
                )
                line = session.prompt(prompt_text)
            except (EOFError, KeyboardInterrupt):
                print()
                break

            _publish_stdin(line)
            output = registry.dispatch(state, line)
            if output is None:
                break
            if output:
                print(output)

            # Drain stdout after command (catches output from llm/process runs)
            _drain_io()
