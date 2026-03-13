"""Asana capability — create and manage Asana tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from cogos.capabilities._secrets_helper import fetch_secret
from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

try:
    import asana
except ImportError:
    asana = None  # type: ignore[assignment]


# ── IO Models ────────────────────────────────────────────────


class TaskResult(BaseModel):
    id: str
    name: str
    project: str = ""
    status: str = ""
    url: str = ""


class TaskSummary(BaseModel):
    id: str
    name: str
    assignee: str = ""
    due_on: str = ""
    completed: bool = False


class CommentResult(BaseModel):
    id: str
    task_id: str


class AsanaError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────

SECRET_KEY = "cogent/{cogent}/asana"


class AsanaCapability(Capability):
    """Asana task management.

    Usage:
        asana.create_task("project-id", "Task name", notes="Details")
        asana.list_tasks("project-id")
    """

    ALL_OPS = {"create_task", "update_task", "list_tasks", "add_comment"}

    def __init__(self, repo, process_id) -> None:
        super().__init__(repo, process_id)
        self._api_key: str | None = None
        self._client = None

    def _get_client(self):
        if self._client is None:
            if self._api_key is None:
                self._api_key = fetch_secret(SECRET_KEY, field="access_token")
            config = asana.Configuration()
            config.access_token = self._api_key
            self._client = asana.ApiClient(config)
        return self._client

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        for key in ("ops", "projects"):
            old = existing.get(key)
            new = requested.get(key)
            if old is not None and new is not None:
                result[key] = [v for v in old if v in new]
            elif old is not None:
                result[key] = old
            elif new is not None:
                result[key] = new
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")
        allowed_projects = self._scope.get("projects")
        if allowed_projects is not None:
            project = context.get("project", "")
            if project and str(project) not in allowed_projects:
                raise PermissionError(
                    f"Project '{project}' not in allowed list: {allowed_projects}"
                )

    def create_task(
        self,
        project: str,
        name: str,
        notes: str = "",
        assignee: str | None = None,
        due_on: str | None = None,
    ) -> TaskResult | AsanaError:
        """Create a task in an Asana project."""
        self._check("create_task", project=project)
        try:
            client = self._get_client()
            api = asana.TasksApi(client)
            body = {"data": {"projects": [project], "name": name}}
            if notes:
                body["data"]["notes"] = notes
            if assignee:
                body["data"]["assignee"] = assignee
            if due_on:
                body["data"]["due_on"] = due_on
            task = api.create_task(body)
            data = task.get("data", task) if isinstance(task, dict) else task
            gid = data["gid"] if isinstance(data, dict) else data.gid
            task_name = data.get("name", name) if isinstance(data, dict) else getattr(data, "name", name)
            url = data.get("permalink_url", "") if isinstance(data, dict) else getattr(data, "permalink_url", "")
            return TaskResult(id=str(gid), name=task_name, project=project, url=url)
        except Exception as exc:
            return AsanaError(error=str(exc))

    def update_task(self, task_id: str, **fields) -> TaskResult | AsanaError:
        """Update fields on an existing task."""
        self._check("update_task")
        try:
            client = self._get_client()
            api = asana.TasksApi(client)
            body = {"data": fields}
            task = api.update_task(body, task_id)
            data = task.get("data", task) if isinstance(task, dict) else task
            gid = data["gid"] if isinstance(data, dict) else data.gid
            name = data.get("name", "") if isinstance(data, dict) else getattr(data, "name", "")
            url = data.get("permalink_url", "") if isinstance(data, dict) else getattr(data, "permalink_url", "")
            return TaskResult(id=str(gid), name=name, url=url)
        except Exception as exc:
            return AsanaError(error=str(exc))

    def list_tasks(self, project: str, limit: int = 50) -> list[TaskSummary] | AsanaError:
        """List tasks in a project."""
        self._check("list_tasks", project=project)
        try:
            client = self._get_client()
            api = asana.TasksApi(client)
            opts = {"limit": limit, "opt_fields": "name,completed,assignee.name,due_on"}
            tasks = api.get_tasks_for_project(project, opts)
            result = []
            items = tasks.get("data", tasks) if isinstance(tasks, dict) else tasks
            for t in items:
                if isinstance(t, dict):
                    assignee_obj = t.get("assignee")
                    assignee_name = assignee_obj.get("name", "") if isinstance(assignee_obj, dict) else ""
                    result.append(TaskSummary(
                        id=t["gid"],
                        name=t.get("name", ""),
                        assignee=assignee_name,
                        due_on=t.get("due_on") or "",
                        completed=t.get("completed", False),
                    ))
                else:
                    assignee_obj = getattr(t, "assignee", None)
                    assignee_name = getattr(assignee_obj, "name", "") if assignee_obj else ""
                    result.append(TaskSummary(
                        id=str(t.gid),
                        name=getattr(t, "name", ""),
                        assignee=assignee_name,
                        due_on=getattr(t, "due_on", "") or "",
                        completed=getattr(t, "completed", False),
                    ))
            return result
        except Exception as exc:
            return AsanaError(error=str(exc))

    def add_comment(self, task_id: str, text: str) -> CommentResult | AsanaError:
        """Add a comment to a task."""
        self._check("add_comment")
        try:
            client = self._get_client()
            api = asana.StoriesApi(client)
            body = {"data": {"text": text}}
            story = api.create_story_for_task(body, task_id)
            data = story.get("data", story) if isinstance(story, dict) else story
            gid = data["gid"] if isinstance(data, dict) else data.gid
            return CommentResult(id=str(gid), task_id=task_id)
        except Exception as exc:
            return AsanaError(error=str(exc))

    def __repr__(self) -> str:
        return "<AsanaCapability create_task() update_task() list_tasks() add_comment()>"
