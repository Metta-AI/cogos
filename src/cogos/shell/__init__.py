"""CogentShell — interactive Unix-like shell for CogOS."""

from __future__ import annotations


class CogentShell:
    """Main shell class — instantiated by the CLI entry point."""

    def __init__(self, cogent_name: str) -> None:
        self.cogent_name = cogent_name

    def run(self) -> None:
        """Start the interactive shell loop."""
        from cogos.db.factory import create_repository
        from cogos.shell.commands import ShellState, build_registry
        from cogos.shell.completer import ShellCompleter
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import FileHistory

        repo = create_repository()
        state = ShellState(cogent_name=self.cogent_name, repo=repo, cwd="")

        try:
            import boto3
            state.bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-1")
        except Exception:
            pass

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

        print(f"CogOS shell for \033[1;36m{self.cogent_name}\033[0m (type 'help' for commands, 'exit' to quit)")

        while True:
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

            output = registry.dispatch(state, line)
            if output is None:
                break
            if output:
                print(output)
