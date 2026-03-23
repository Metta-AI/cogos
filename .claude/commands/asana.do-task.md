Pick an incomplete task from the Cogents Asana project, work on it, comment with status, and summarize.

## Constants

- **Workspace**: Softmax (`1209016784099267`)
- **Project**: Cogents (`1213428766379931`)

## Steps

1. **Fetch incomplete tasks** from the Cogents project:
   - Use `asana_get_tasks` with project `1213428766379931`, `opt_fields`: `name,notes,completed,assignee.name,due_on`
   - Filter to incomplete tasks only
   - If no incomplete tasks exist, tell the user and stop

2. **Build a shortlist of candidate tasks**:
   - Filter to tasks that are: incomplete, unassigned (or assigned to current user), and look like coding/engineering work actionable from this repo
   - Skip tasks that are clearly blocked or not actionable
   - Sort by due date (sooner first), but keep the top 3-5 candidates

3. **Pick randomly from the shortlist** (concurrency-safe selection):
   - From the shortlist of 3-5 candidates, pick one **at random** (not deterministically the "best" one). This prevents multiple concurrent agents from all choosing the same task.
   - If only 1 candidate exists, pick that one.

4. **Claim the task via assignment** (optimistic lock):
   - Use `asana_update_task` to assign the task to `me` immediately
   - Then wait ~2 seconds (`sleep 2` via Bash) to allow other concurrent agents to also attempt assignment
   - Re-read the task with `asana_get_task` (opt_fields: `assignee.name,assignee.gid`) to verify YOU are still the assignee
   - Also check recent stories with `asana_get_stories_for_task` (limit 5) for other "picking up this task" comments in the last 2 minutes
   - **If someone else is assigned or another agent already commented**: skip this task, go back to step 3 and pick a different candidate from the shortlist
   - **If you are the assignee and no other agent claimed it**: proceed

5. **Comment "starting work"** on the task:
   - Use `asana_create_task_story` with a comment like: "Claude Code agent picking up this task. Will comment with results."

6. **Get full task details**:
   - Use `asana_get_task` with the chosen task_id and `opt_fields`: `name,notes,html_notes,assignee,due_on,dependencies,custom_fields`
   - Read the task description carefully to understand what needs to be done
   - Show the user which task you picked and why, with a link: `https://app.asana.com/0/1213428766379931/<task_gid>`

7. **Do the work**:
   - Analyze the task requirements
   - Explore the codebase as needed to understand context
   - Implement the changes (write code, fix bugs, add features, etc.)
   - Run `/vet` to check for issues
   - If the task is not something you can do from this repo (e.g., it's a manual task, requires external access you don't have), comment on the task explaining why and pick a different task (go back to step 2)

8. **Test your changes**:
   - Run relevant tests if they exist
   - Verify the changes work as expected

9. **Comment results on the task**:
   - Use `asana_create_task_story` with a detailed comment:
     - What was done
     - Files changed
     - Any caveats or follow-up needed
   - If the task is fully complete, mark it completed with `asana_update_task` (`completed: true`)
   - If partially done, leave it open and explain what remains in the comment

10. **Submit changes** using the user's preferred submit workflow (check their CLAUDE.md for preference between `/submit.gt` and `/submit`; default to `/submit` if unspecified)

11. **Print a summary** of what was accomplished:
    - Task name and link
    - What was done
    - Files changed
    - Whether the task was marked complete
    - Any follow-up items
