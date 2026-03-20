Pick an incomplete task from the Cogents Asana project, work on it, comment with status, and summarize.

## Constants

- **Workspace**: Softmax (`1209016784099267`)
- **Project**: Cogents (`1213428766379931`)

## Steps

1. **Fetch incomplete tasks** from the Cogents project:
   - Use `asana_get_tasks` with project `1213428766379931`, `opt_fields`: `name,notes,completed,assignee.name,due_on`
   - Filter to incomplete tasks only
   - If no incomplete tasks exist, tell the user and stop

2. **Pick the best task to work on**:
   - Prefer tasks assigned to no one or to the current user
   - Prefer tasks with due dates sooner
   - Prefer tasks that look like coding/engineering work in this repo
   - Skip tasks that are clearly blocked or not actionable from this repo
   - Show the user which task you picked and why, with a link: `https://app.asana.com/0/1213428766379931/<task_gid>`

3. **Get full task details**:
   - Use `asana_get_task` with the chosen task_id and `opt_fields`: `name,notes,html_notes,assignee,due_on,dependencies,custom_fields`
   - Read the task description carefully to understand what needs to be done

4. **Comment "starting work"** on the task:
   - Use `asana_create_task_story` with a comment like: "🤖 Claude Code agent picking up this task. Will comment with results."

5. **Do the work**:
   - Analyze the task requirements
   - Explore the codebase as needed to understand context
   - Implement the changes (write code, fix bugs, add features, etc.)
   - Run `/vet` to check for issues
   - If the task is not something you can do from this repo (e.g., it's a manual task, requires external access you don't have), comment on the task explaining why and pick a different task (go back to step 2)

6. **Test your changes**:
   - Run relevant tests if they exist
   - Verify the changes work as expected

7. **Comment results on the task**:
   - Use `asana_create_task_story` with a detailed comment:
     - What was done
     - Files changed
     - Any caveats or follow-up needed
   - If the task is fully complete, mark it completed with `asana_update_task` (`completed: true`)
   - If partially done, leave it open and explain what remains in the comment

8. **Submit changes** using the user's preferred submit workflow (check their CLAUDE.md for preference between `/submit.gt` and `/submit`; default to `/submit` if unspecified)

9. **Print a summary** of what was accomplished:
   - Task name and link
   - What was done
   - Files changed
   - Whether the task was marked complete
   - Any follow-up items
