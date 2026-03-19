# Asana API

Create, search, and manage Asana tasks, projects, and users.

## Discovering context

```python
# List workspaces to find workspace IDs
workspaces = asana.list_workspaces()
# [{"id": "123", "name": "My Workspace"}]

# List projects in a workspace
projects = asana.list_projects(workspace="123")
# [ProjectSummary(id, name, status, url)]

# Find a user by name or email
users = asana.find_user(workspace="123", query="david")
# [{"id": "456", "name": "David Bloomin"}]
```

## Tasks

```python
# List tasks in a project
tasks = asana.list_tasks("project-id", limit=50)

# List MY tasks (authenticated user)
my = asana.my_tasks()

# List tasks for a specific user
tasks = asana.tasks_for_user("user-gid", workspace="workspace-gid")

# Search tasks across a workspace
results = asana.search_tasks("workspace-id", "bug fix", assignee="user-gid", completed=False)

# Get full task details
task = asana.get_task("task-id")
# TaskDetail(id, name, notes, assignee, due_on, completed, project, section, url, custom_fields)

# Create a task
result = asana.create_task("project-id", "Task name", notes="Details", assignee="user-gid", due_on="2026-04-01")

# Update a task
asana.update_task("task-id", name="New name", completed=True)

# Delete a task
asana.delete_task("task-id")
```

## Organization

```python
# List sections in a project (columns/stages)
sections = asana.list_sections("project-id")
# [{"id": "789", "name": "To Do"}, {"id": "790", "name": "In Progress"}]

# Move a task to a section
asana.add_to_section("task-id", "section-id")

# Set task parent (subtask)
asana.set_parent("subtask-id", "parent-task-id")

# Add followers to a task
asana.add_followers("task-id", ["user-gid-1", "user-gid-2"])

# Add a comment
asana.add_comment("task-id", "This is done!")
```

## Project details

```python
project = asana.get_project("project-id")
# ProjectDetail(id, name, notes, status, url, team)
```

## Typical workflow: "list tasks assigned to David"

```python
# 1. Find workspace
workspaces = asana.list_workspaces()
ws_id = workspaces[0]["id"]

# 2. Find user
users = asana.find_user(workspace=ws_id, query="David")
user_id = users[0]["id"]

# 3. Get their tasks
tasks = asana.tasks_for_user(user_id, workspace=ws_id)
for t in tasks:
    print(f"{'✓' if t.completed else '○'} {t.name} (due: {t.due_on})")
```
