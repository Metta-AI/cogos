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


class TaskDetail(BaseModel):
    id: str
    name: str
    notes: str = ""
    assignee: str = ""
    due_on: str = ""
    completed: bool = False
    project: str = ""
    section: str = ""
    url: str = ""
    custom_fields: dict = {}


class ProjectSummary(BaseModel):
    id: str
    name: str
    status: str = ""
    url: str = ""


class ProjectDetail(BaseModel):
    id: str
    name: str
    notes: str = ""
    status: str = ""
    url: str = ""
    team: str = ""


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

    ALL_OPS = {
        "create_task",
        "update_task",
        "list_tasks",
        "my_tasks",
        "add_comment",
        "get_task",
        "delete_task",
        "search_tasks",
        "list_projects",
        "get_project",
        "list_workspaces",
        "list_sections",
        "add_to_section",
        "add_followers",
        "set_parent",
        "find_user",
        "tasks_for_user",
    }

    def __init__(self, repo, process_id) -> None:
        super().__init__(repo, process_id)
        self._api_key: str | None = None
        self._client = None
        self._username: str | None = None

    def username(self) -> str:
        """The Asana username for this cogent."""
        if self._username is None:
            try:
                self._username = fetch_secret("cogent/{cogent}/asana", field="username") or ""
            except Exception:
                self._username = ""
        return self._username

    def profile(self) -> str:
        """Return Asana identity as markdown for prompt injection."""
        name = self.username()
        if name:
            return f"- **Asana Username:** {name}\n"
        return ""

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
                raise PermissionError(f"Project '{project}' not in allowed list: {allowed_projects}")

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
            task = api.create_task(body, {})
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
            task = api.update_task(body, task_id, {})
            data = task.get("data", task) if isinstance(task, dict) else task
            gid = data["gid"] if isinstance(data, dict) else data.gid
            name = data.get("name", "") if isinstance(data, dict) else getattr(data, "name", "")
            url = data.get("permalink_url", "") if isinstance(data, dict) else getattr(data, "permalink_url", "")
            return TaskResult(id=str(gid), name=name, url=url)
        except Exception as exc:
            return AsanaError(error=str(exc))

    def my_tasks(self, workspace: str | None = None, limit: int = 50) -> list[TaskSummary] | AsanaError:
        """List all tasks assigned to the authenticated user."""
        self._check("my_tasks")
        try:
            client = self._get_client()
            users_api = asana.UserTaskListsApi(client)
            tasks_api = asana.TasksApi(client)
            me = asana.UsersApi(client).get_user("me", {"opt_fields": "gid,workspaces.gid"})
            me_data = me.get("data", me) if isinstance(me, dict) else me
            me_gid = me_data["gid"] if isinstance(me_data, dict) else me_data.gid
            ws_gid = workspace
            if not ws_gid:
                if isinstance(me_data, dict):
                    workspaces = me_data.get("workspaces", [])
                else:
                    workspaces = getattr(me_data, "workspaces", [])
                if workspaces:
                    ws = workspaces[0]
                    ws_gid = ws["gid"] if isinstance(ws, dict) else ws.gid
                else:
                    return AsanaError(error="No workspaces found")
            utl = users_api.get_user_task_list_for_user(me_gid, ws_gid, {})
            utl_data = utl.get("data", utl) if isinstance(utl, dict) else utl
            utl_gid = utl_data["gid"] if isinstance(utl_data, dict) else utl_data.gid
            opts = {"limit": limit, "opt_fields": "name,completed,assignee.name,due_on"}
            tasks = tasks_api.get_tasks_for_user_task_list(utl_gid, opts)
            result = []
            items = tasks.get("data", tasks) if isinstance(tasks, dict) else tasks
            for t in items:
                if isinstance(t, dict):
                    assignee_obj = t.get("assignee")
                    assignee_name = assignee_obj.get("name", "") if isinstance(assignee_obj, dict) else ""
                    result.append(
                        TaskSummary(
                            id=t["gid"],
                            name=t.get("name", ""),
                            assignee=assignee_name,
                            due_on=t.get("due_on") or "",
                            completed=t.get("completed", False),
                        )
                    )
                else:
                    assignee_obj = getattr(t, "assignee", None)
                    assignee_name = getattr(assignee_obj, "name", "") if assignee_obj else ""
                    result.append(
                        TaskSummary(
                            id=str(t.gid),
                            name=getattr(t, "name", ""),
                            assignee=assignee_name,
                            due_on=getattr(t, "due_on", "") or "",
                            completed=getattr(t, "completed", False),
                        )
                    )
            return result
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
                    result.append(
                        TaskSummary(
                            id=t["gid"],
                            name=t.get("name", ""),
                            assignee=assignee_name,
                            due_on=t.get("due_on") or "",
                            completed=t.get("completed", False),
                        )
                    )
                else:
                    assignee_obj = getattr(t, "assignee", None)
                    assignee_name = getattr(assignee_obj, "name", "") if assignee_obj else ""
                    result.append(
                        TaskSummary(
                            id=str(t.gid),
                            name=getattr(t, "name", ""),
                            assignee=assignee_name,
                            due_on=getattr(t, "due_on", "") or "",
                            completed=getattr(t, "completed", False),
                        )
                    )
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
            story = api.create_story_for_task(body, task_id, {})
            data = story.get("data", story) if isinstance(story, dict) else story
            gid = data["gid"] if isinstance(data, dict) else data.gid
            return CommentResult(id=str(gid), task_id=task_id)
        except Exception as exc:
            return AsanaError(error=str(exc))

    def get_task(self, task_id: str) -> TaskDetail | AsanaError:
        """Get detailed information about a single task."""
        self._check("get_task")
        try:
            client = self._get_client()
            api = asana.TasksApi(client)
            opts = {
                "opt_fields": (
                    "name,notes,assignee.name,due_on,completed,"
                    "memberships.project.name,memberships.section.name,"
                    "permalink_url,custom_fields.name,custom_fields.display_value"
                )
            }
            task = api.get_task(task_id, opts)
            data = task.get("data", task) if isinstance(task, dict) else task

            if isinstance(data, dict):
                gid = data["gid"]
                name = data.get("name", "")
                notes = data.get("notes", "")
                assignee_obj = data.get("assignee")
                assignee_name = assignee_obj.get("name", "") if isinstance(assignee_obj, dict) else ""
                due_on = data.get("due_on") or ""
                completed = data.get("completed", False)
                url = data.get("permalink_url", "")
                memberships = data.get("memberships", [])
                project = ""
                section = ""
                if memberships:
                    m = memberships[0]
                    proj_obj = m.get("project")
                    sec_obj = m.get("section")
                    if isinstance(proj_obj, dict):
                        project = proj_obj.get("name", "")
                    if isinstance(sec_obj, dict):
                        section = sec_obj.get("name", "")
                cf_list = data.get("custom_fields", [])
                custom_fields = {}
                for cf in cf_list:
                    cf_name = cf.get("name", "")
                    cf_val = cf.get("display_value", "")
                    if cf_name:
                        custom_fields[cf_name] = cf_val
            else:
                gid = data.gid
                name = getattr(data, "name", "")
                notes = getattr(data, "notes", "")
                assignee_obj = getattr(data, "assignee", None)
                assignee_name = getattr(assignee_obj, "name", "") if assignee_obj else ""
                due_on = getattr(data, "due_on", "") or ""
                completed = getattr(data, "completed", False)
                url = getattr(data, "permalink_url", "")
                memberships = getattr(data, "memberships", [])
                project = ""
                section = ""
                if memberships:
                    m = memberships[0]
                    proj_obj = getattr(m, "project", None)
                    sec_obj = getattr(m, "section", None)
                    if proj_obj:
                        project = getattr(proj_obj, "name", "")
                    if sec_obj:
                        section = getattr(sec_obj, "name", "")
                cf_list = getattr(data, "custom_fields", [])
                custom_fields = {}
                for cf in cf_list:
                    cf_name = getattr(cf, "name", "")
                    cf_val = getattr(cf, "display_value", "")
                    if cf_name:
                        custom_fields[cf_name] = cf_val

            return TaskDetail(
                id=str(gid),
                name=name,
                notes=notes,
                assignee=assignee_name,
                due_on=due_on,
                completed=completed,
                project=project,
                section=section,
                url=url,
                custom_fields=custom_fields,
            )
        except Exception as exc:
            return AsanaError(error=str(exc))

    def delete_task(self, task_id: str) -> dict | AsanaError:
        """Delete a task by ID."""
        self._check("delete_task")
        try:
            client = self._get_client()
            api = asana.TasksApi(client)
            api.delete_task(task_id)
            return {"ok": True}
        except Exception as exc:
            return AsanaError(error=str(exc))

    def search_tasks(
        self,
        workspace: str,
        text: str,
        assignee: str | None = None,
        project: str | None = None,
        completed: bool | None = None,
        limit: int = 50,
    ) -> list[TaskSummary] | AsanaError:
        """Search tasks in a workspace."""
        self._check("search_tasks")
        try:
            client = self._get_client()
            api = asana.TasksApi(client)
            opts: dict = {
                "text": text,
                "limit": limit,
                "opt_fields": "name,completed,assignee.name,due_on",
            }
            if assignee:
                opts["assignee.any"] = assignee
            if project:
                opts["projects.any"] = project
            if completed is not None:
                opts["completed"] = completed
            tasks = api.search_tasks_for_workspace(workspace, opts)
            items = tasks.get("data", tasks) if isinstance(tasks, dict) else tasks
            result = []
            for t in items:
                if isinstance(t, dict):
                    assignee_obj = t.get("assignee")
                    assignee_name = assignee_obj.get("name", "") if isinstance(assignee_obj, dict) else ""
                    result.append(
                        TaskSummary(
                            id=t["gid"],
                            name=t.get("name", ""),
                            assignee=assignee_name,
                            due_on=t.get("due_on") or "",
                            completed=t.get("completed", False),
                        )
                    )
                else:
                    assignee_obj = getattr(t, "assignee", None)
                    assignee_name = getattr(assignee_obj, "name", "") if assignee_obj else ""
                    result.append(
                        TaskSummary(
                            id=str(t.gid),
                            name=getattr(t, "name", ""),
                            assignee=assignee_name,
                            due_on=getattr(t, "due_on", "") or "",
                            completed=getattr(t, "completed", False),
                        )
                    )
            return result
        except Exception as exc:
            return AsanaError(error=str(exc))

    def list_projects(self, workspace: str | None = None, limit: int = 50) -> list[ProjectSummary] | AsanaError:
        """List projects, optionally filtered by workspace."""
        self._check("list_projects")
        try:
            client = self._get_client()
            api = asana.ProjectsApi(client)
            opts: dict = {
                "limit": limit,
                "opt_fields": "name,current_status_update.status_type,permalink_url",
            }
            if workspace:
                opts["workspace"] = workspace
            projects = api.get_projects(opts)
            items = projects.get("data", projects) if isinstance(projects, dict) else projects
            result = []
            for p in items:
                if isinstance(p, dict):
                    status_obj = p.get("current_status_update")
                    status = status_obj.get("status_type", "") if isinstance(status_obj, dict) else ""
                    result.append(
                        ProjectSummary(
                            id=p["gid"],
                            name=p.get("name", ""),
                            status=status,
                            url=p.get("permalink_url", ""),
                        )
                    )
                else:
                    status_obj = getattr(p, "current_status_update", None)
                    status = getattr(status_obj, "status_type", "") if status_obj else ""
                    result.append(
                        ProjectSummary(
                            id=str(p.gid),
                            name=getattr(p, "name", ""),
                            status=status,
                            url=getattr(p, "permalink_url", ""),
                        )
                    )
            return result
        except Exception as exc:
            return AsanaError(error=str(exc))

    def get_project(self, project_id: str) -> ProjectDetail | AsanaError:
        """Get detailed information about a project."""
        self._check("get_project")
        try:
            client = self._get_client()
            api = asana.ProjectsApi(client)
            opts = {"opt_fields": "name,notes,current_status_update.status_type,permalink_url,team.name"}
            project = api.get_project(project_id, opts)
            data = project.get("data", project) if isinstance(project, dict) else project

            if isinstance(data, dict):
                gid = data["gid"]
                name = data.get("name", "")
                notes = data.get("notes", "")
                status_obj = data.get("current_status_update")
                status = status_obj.get("status_type", "") if isinstance(status_obj, dict) else ""
                url = data.get("permalink_url", "")
                team_obj = data.get("team")
                team = team_obj.get("name", "") if isinstance(team_obj, dict) else ""
            else:
                gid = data.gid
                name = getattr(data, "name", "")
                notes = getattr(data, "notes", "")
                status_obj = getattr(data, "current_status_update", None)
                status = getattr(status_obj, "status_type", "") if status_obj else ""
                url = getattr(data, "permalink_url", "")
                team_obj = getattr(data, "team", None)
                team = getattr(team_obj, "name", "") if team_obj else ""

            return ProjectDetail(
                id=str(gid),
                name=name,
                notes=notes,
                status=status,
                url=url,
                team=team,
            )
        except Exception as exc:
            return AsanaError(error=str(exc))

    def list_workspaces(self) -> list[dict] | AsanaError:
        """List all accessible workspaces."""
        self._check("list_workspaces")
        try:
            client = self._get_client()
            api = asana.WorkspacesApi(client)
            workspaces = api.get_workspaces({"opt_fields": "name"})
            items = workspaces.get("data", workspaces) if isinstance(workspaces, dict) else workspaces
            result = []
            for w in items:
                if isinstance(w, dict):
                    result.append({"id": w["gid"], "name": w.get("name", "")})
                else:
                    result.append({"id": str(w.gid), "name": getattr(w, "name", "")})
            return result
        except Exception as exc:
            return AsanaError(error=str(exc))

    def list_sections(self, project: str) -> list[dict] | AsanaError:
        """List sections in a project."""
        self._check("list_sections", project=project)
        try:
            client = self._get_client()
            api = asana.SectionsApi(client)
            sections = api.get_sections_for_project(project, {"opt_fields": "name"})
            items = sections.get("data", sections) if isinstance(sections, dict) else sections
            result = []
            for s in items:
                if isinstance(s, dict):
                    result.append({"id": s["gid"], "name": s.get("name", "")})
                else:
                    result.append({"id": str(s.gid), "name": getattr(s, "name", "")})
            return result
        except Exception as exc:
            return AsanaError(error=str(exc))

    def add_to_section(self, task_id: str, section_id: str) -> dict | AsanaError:
        """Move / add a task to a section."""
        self._check("add_to_section")
        try:
            client = self._get_client()
            api = asana.SectionsApi(client)
            opts = {"body": {"data": {"task": task_id}}}
            api.add_task_for_section(section_id, opts)
            return {"ok": True}
        except Exception as exc:
            return AsanaError(error=str(exc))

    def add_followers(self, task_id: str, followers: list[str]) -> TaskResult | AsanaError:
        """Add followers to a task."""
        self._check("add_followers")
        try:
            client = self._get_client()
            api = asana.TasksApi(client)
            body = {"data": {"followers": followers}}
            task = api.add_followers_for_task(body, task_id, {})
            data = task.get("data", task) if isinstance(task, dict) else task
            gid = data["gid"] if isinstance(data, dict) else data.gid
            name = data.get("name", "") if isinstance(data, dict) else getattr(data, "name", "")
            url = data.get("permalink_url", "") if isinstance(data, dict) else getattr(data, "permalink_url", "")
            return TaskResult(id=str(gid), name=name, url=url)
        except Exception as exc:
            return AsanaError(error=str(exc))

    def set_parent(self, task_id: str, parent_id: str) -> TaskResult | AsanaError:
        """Set the parent of a task (make it a subtask)."""
        self._check("set_parent")
        try:
            client = self._get_client()
            api = asana.TasksApi(client)
            body = {"data": {"parent": parent_id}}
            task = api.set_parent_for_task(body, task_id, {})
            data = task.get("data", task) if isinstance(task, dict) else task
            gid = data["gid"] if isinstance(data, dict) else data.gid
            name = data.get("name", "") if isinstance(data, dict) else getattr(data, "name", "")
            url = data.get("permalink_url", "") if isinstance(data, dict) else getattr(data, "permalink_url", "")
            return TaskResult(id=str(gid), name=name, url=url)
        except Exception as exc:
            return AsanaError(error=str(exc))

    def find_user(self, workspace: str, query: str) -> list[dict] | AsanaError:
        """Search for users by name or email in a workspace."""
        self._check("find_user")
        try:
            client = self._get_client()
            api = asana.TypeaheadApi(client)
            opts = {"query": query, "count": 10}
            results = api.typeahead_for_workspace(workspace, "user", opts)
            items = results.get("data", results) if isinstance(results, dict) else results
            out = []
            for u in items:
                if isinstance(u, dict):
                    out.append({"id": u["gid"], "name": u.get("name", "")})
                else:
                    out.append({"id": str(u.gid), "name": getattr(u, "name", "")})
            return out
        except Exception as exc:
            return AsanaError(error=str(exc))

    def tasks_for_user(
        self,
        user_id: str,
        workspace: str | None = None,
        limit: int = 50,
    ) -> list[TaskSummary] | AsanaError:
        """List tasks assigned to a specific user by their Asana GID."""
        self._check("tasks_for_user")
        try:
            client = self._get_client()
            users_api = asana.UserTaskListsApi(client)
            tasks_api = asana.TasksApi(client)
            if not workspace:
                me = asana.UsersApi(client).get_user("me", {"opt_fields": "gid,workspaces.gid"})
                me_data = me.get("data", me) if isinstance(me, dict) else me
                if isinstance(me_data, dict):
                    workspaces = me_data.get("workspaces", [])
                else:
                    workspaces = getattr(me_data, "workspaces", [])
                if workspaces:
                    ws = workspaces[0]
                    workspace = ws["gid"] if isinstance(ws, dict) else ws.gid
                else:
                    return AsanaError(error="No workspaces found")
            utl = users_api.get_user_task_list_for_user(user_id, workspace, {})
            utl_data = utl.get("data", utl) if isinstance(utl, dict) else utl
            utl_gid = utl_data["gid"] if isinstance(utl_data, dict) else utl_data.gid
            opts = {"limit": limit, "opt_fields": "name,completed,assignee.name,due_on"}
            tasks = tasks_api.get_tasks_for_user_task_list(utl_gid, opts)
            items = tasks.get("data", tasks) if isinstance(tasks, dict) else tasks
            result = []
            for t in items:
                if isinstance(t, dict):
                    assignee_obj = t.get("assignee")
                    assignee_name = assignee_obj.get("name", "") if isinstance(assignee_obj, dict) else ""
                    result.append(
                        TaskSummary(
                            id=t["gid"],
                            name=t.get("name", ""),
                            assignee=assignee_name,
                            due_on=t.get("due_on") or "",
                            completed=t.get("completed", False),
                        )
                    )
                else:
                    assignee_obj = getattr(t, "assignee", None)
                    assignee_name = getattr(assignee_obj, "name", "") if assignee_obj else ""
                    result.append(
                        TaskSummary(
                            id=str(t.gid),
                            name=getattr(t, "name", ""),
                            assignee=assignee_name,
                            due_on=getattr(t, "due_on", "") or "",
                            completed=getattr(t, "completed", False),
                        )
                    )
            return result
        except Exception as exc:
            return AsanaError(error=str(exc))

    def __repr__(self) -> str:
        return (
            "<AsanaCapability create_task() update_task() list_tasks() "
            "get_task() delete_task() search_tasks() list_projects() "
            "get_project() list_workspaces() list_sections() "
            "add_to_section() add_followers() set_parent() add_comment()>"
        )
