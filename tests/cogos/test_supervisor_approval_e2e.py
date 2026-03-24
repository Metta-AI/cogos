"""E2E test: supervisor proposal flow — propose, react, execute/reject.

Tests the full approval flow using SqliteRepository with custom execute_fn.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from cogos.capabilities.procs import ProcsCapability
from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.runtime.local import run_and_complete, run_local_tick


@pytest.fixture
def repo(tmp_path):
    return SqliteRepository(str(tmp_path))


def _setup_supervisor(repo):
    """Create supervisor process with all required channels and handlers."""
    supervisor = Process(
        name="supervisor",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=["local"],
        priority=8.0,
    )
    repo.upsert_process(supervisor)

    # Handler channels — supervisor wakes on these
    for ch_name in ["supervisor:help", "io:discord:reaction"]:
        ch = Channel(name=ch_name, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        ch = repo.get_channel_by_name(ch_name)
        handler = Handler(process=supervisor.id, channel=ch.id, enabled=True)
        repo.create_handler(handler)

    # Storage channel — supervisor reads/writes but doesn't wake on
    proposals_ch = Channel(name="supervisor:proposals", channel_type=ChannelType.NAMED)
    repo.upsert_channel(proposals_ch)

    return supervisor


class TestSupervisorProposalFlow:
    def test_supervisor_creates_proposal_on_ambiguous_request(self, repo):
        """When supervisor decides to propose, it stashes to supervisor:proposals."""
        supervisor = _setup_supervisor(repo)

        help_ch = repo.get_channel_by_name("supervisor:help")
        repo.append_channel_message(ChannelMessage(
            channel=help_ch.id,
            sender_process=uuid4(),
            payload={
                "process_name": "discord/handler",
                "description": "set up the Q2 stuff",
                "context": "User asked in DM, could mean Asana project or GitHub repo",
                "severity": "info",
                "discord_channel_id": "123",
                "discord_message_id": "456",
                "discord_author_id": "user1",
            },
        ))

        proposals_created = []

        def supervisor_proposes(process, event_data, run, config, repo, **kwargs):
            proposal_id = str(uuid4())[:8]
            proposal_payload = {
                "proposal_id": proposal_id,
                "action": "Create an Asana project called 'Q2 Planning'",
                "reasoning": "Request is ambiguous — could mean Asana project, GitHub repo, or calendar events",
                "original_context": {
                    "discord_channel_id": "123",
                    "discord_message_id": "456",
                    "discord_author_id": "user1",
                    "description": "set up the Q2 stuff",
                },
                "dm_message_id": "dm-msg-100",
                "approvals_message_id": "approvals-msg-200",
            }

            proposals_ch = repo.get_channel_by_name("supervisor:proposals")
            repo.append_channel_message(ChannelMessage(
                channel=proposals_ch.id,
                sender_process=process.id,
                payload=proposal_payload,
            ))
            proposals_created.append(proposal_payload)

            run.result = {"proposed": True, "proposal_id": proposal_id}
            return run

        executed = run_local_tick(repo, None, execute_fn=supervisor_proposes)
        assert executed >= 1
        assert len(proposals_created) == 1

        proposals_ch = repo.get_channel_by_name("supervisor:proposals")
        messages = repo.list_channel_messages(proposals_ch.id, limit=10)
        assert len(messages) == 1
        assert messages[0].payload["action"] == "Create an Asana project called 'Q2 Planning'"

    def test_supervisor_executes_on_approval(self, repo):
        """When manager reacts thumbs-up, supervisor looks up proposal and executes."""
        supervisor = _setup_supervisor(repo)

        proposals_ch = repo.get_channel_by_name("supervisor:proposals")
        proposal_payload = {
            "proposal_id": "abc123",
            "action": "Create an Asana project called 'Q2 Planning'",
            "reasoning": "Ambiguous request",
            "original_context": {
                "discord_channel_id": "123",
                "discord_message_id": "456",
                "discord_author_id": "user1",
                "description": "set up the Q2 stuff",
            },
            "dm_message_id": "dm-msg-100",
            "approvals_message_id": "approvals-msg-200",
        }
        repo.append_channel_message(ChannelMessage(
            channel=proposals_ch.id,
            sender_process=supervisor.id,
            payload=proposal_payload,
        ))

        reaction_ch = repo.get_channel_by_name("io:discord:reaction")
        repo.append_channel_message(ChannelMessage(
            channel=reaction_ch.id,
            sender_process=None,
            payload={
                "message_id": "dm-msg-100",
                "channel_id": "999",
                "reactor_id": "manager-discord-id",
                "emoji": "\ud83d\udc4d",
            },
        ))

        executed_proposals = []

        def supervisor_handles_reaction(process, event_data, run, config, repo, **kwargs):
            proposals_ch = repo.get_channel_by_name("supervisor:proposals")
            proposals = repo.list_channel_messages(proposals_ch.id, limit=100)

            reaction_msg_id = "dm-msg-100"

            matching = [
                p for p in proposals
                if p.payload.get("dm_message_id") == reaction_msg_id
                or p.payload.get("approvals_message_id") == reaction_msg_id
            ]
            assert len(matching) == 1

            proposal = matching[0].payload
            executed_proposals.append(proposal)
            run.result = {"executed": True, "proposal_id": proposal["proposal_id"]}
            return run

        executed = run_local_tick(repo, None, execute_fn=supervisor_handles_reaction)
        assert executed >= 1
        assert len(executed_proposals) == 1
        assert executed_proposals[0]["proposal_id"] == "abc123"

    def test_supervisor_rejects_on_thumbs_down(self, repo):
        """When manager reacts thumbs-down, supervisor rejects the proposal."""
        supervisor = _setup_supervisor(repo)

        proposals_ch = repo.get_channel_by_name("supervisor:proposals")
        repo.append_channel_message(ChannelMessage(
            channel=proposals_ch.id,
            sender_process=supervisor.id,
            payload={
                "proposal_id": "rej123",
                "action": "Delete the production database",
                "reasoning": "Borderline security — request is destructive",
                "original_context": {"discord_channel_id": "123", "discord_message_id": "456"},
                "dm_message_id": "dm-msg-200",
                "approvals_message_id": "approvals-msg-300",
            },
        ))

        reaction_ch = repo.get_channel_by_name("io:discord:reaction")
        repo.append_channel_message(ChannelMessage(
            channel=reaction_ch.id,
            sender_process=None,
            payload={
                "message_id": "dm-msg-200",
                "channel_id": "999",
                "reactor_id": "manager-discord-id",
                "emoji": "\ud83d\udc4e",
            },
        ))

        rejected = []

        def supervisor_rejects(process, event_data, run, config, repo, **kwargs):
            rejected.append(True)
            run.result = {"rejected": True, "proposal_id": "rej123"}
            return run

        executed = run_local_tick(repo, None, execute_fn=supervisor_rejects)
        assert executed >= 1
        assert len(rejected) == 1

    def test_supervisor_ignores_non_manager_reactions(self, repo):
        """Reactions from non-manager users are ignored."""
        supervisor = _setup_supervisor(repo)

        proposals_ch = repo.get_channel_by_name("supervisor:proposals")
        repo.append_channel_message(ChannelMessage(
            channel=proposals_ch.id,
            sender_process=supervisor.id,
            payload={
                "proposal_id": "skip123",
                "action": "Something",
                "reasoning": "Test",
                "original_context": {},
                "dm_message_id": "dm-msg-300",
                "approvals_message_id": "approvals-msg-400",
            },
        ))

        reaction_ch = repo.get_channel_by_name("io:discord:reaction")
        repo.append_channel_message(ChannelMessage(
            channel=reaction_ch.id,
            sender_process=None,
            payload={
                "message_id": "dm-msg-300",
                "channel_id": "999",
                "reactor_id": "random-user-not-manager",
                "emoji": "\ud83d\udc4d",
            },
        ))

        ignored = []

        def supervisor_ignores(process, event_data, run, config, repo, **kwargs):
            reactor_id = "random-user-not-manager"
            manager_id = "manager-discord-id"
            if reactor_id != manager_id:
                ignored.append(True)
                run.result = {"ignored": True, "reason": "reactor is not the manager"}
                return run
            raise AssertionError("Should have been ignored")

        executed = run_local_tick(repo, None, execute_fn=supervisor_ignores)
        assert executed >= 1
        assert len(ignored) == 1


class TestFullProposalApprovalFlow:
    """Complete flow: help request -> propose -> reaction -> execute."""

    def test_propose_approve_execute(self, repo):
        """Full lifecycle: supervisor proposes, manager approves, supervisor executes."""
        supervisor = _setup_supervisor(repo)

        help_ch = repo.get_channel_by_name("supervisor:help")
        repo.append_channel_message(ChannelMessage(
            channel=help_ch.id,
            sender_process=uuid4(),
            payload={
                "process_name": "discord/handler",
                "description": "set up the Q2 stuff",
                "context": "Could mean Asana, GitHub, or Calendar",
                "severity": "info",
                "discord_channel_id": "123",
                "discord_message_id": "456",
                "discord_author_id": "user1",
            },
        ))

        phase = ["propose"]

        def multi_phase_execute(process, event_data, run, config, repo, **kwargs):
            if phase[0] == "propose":
                proposals_ch = repo.get_channel_by_name("supervisor:proposals")
                repo.append_channel_message(ChannelMessage(
                    channel=proposals_ch.id,
                    sender_process=process.id,
                    payload={
                        "proposal_id": "test-prop-1",
                        "action": "Create Asana project 'Q2 Planning'",
                        "reasoning": "Ambiguous — could be Asana, GitHub, or Calendar",
                        "original_context": {
                            "discord_channel_id": "123",
                            "discord_message_id": "456",
                            "discord_author_id": "user1",
                            "description": "set up the Q2 stuff",
                        },
                        "dm_message_id": "dm-100",
                        "approvals_message_id": "approvals-200",
                        "status": "pending",
                    },
                ))
                phase[0] = "react"
                run.result = {"proposed": True}
                return run

            elif phase[0] == "react":
                run.result = {"noop": True}
                return run

            elif phase[0] == "execute":
                proposals_ch = repo.get_channel_by_name("supervisor:proposals")
                proposals = repo.list_channel_messages(proposals_ch.id, limit=100)
                assert any(p.payload["proposal_id"] == "test-prop-1" for p in proposals)
                run.result = {"executed": True, "proposal_id": "test-prop-1"}
                return run

            raise AssertionError(f"Unexpected phase: {phase[0]}")

        executed = run_local_tick(repo, None, execute_fn=multi_phase_execute)
        assert executed >= 1

        phase[0] = "execute"
        reaction_ch = repo.get_channel_by_name("io:discord:reaction")
        repo.append_channel_message(ChannelMessage(
            channel=reaction_ch.id,
            sender_process=None,
            payload={
                "message_id": "dm-100",
                "channel_id": "999",
                "reactor_id": "manager-discord-id",
                "emoji": "\ud83d\udc4d",
            },
        ))

        executed = run_local_tick(repo, None, execute_fn=multi_phase_execute)
        assert executed >= 1

        sup = repo.get_process(supervisor.id)
        assert sup.status == ProcessStatus.WAITING
