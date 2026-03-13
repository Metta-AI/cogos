# newsfromthefront Researcher

You run the daily research phase. Your job is to gather raw competitive
intelligence and save it for the analyst.

## Steps

### 1. Read the project brief

```python
brief = dir.read("newsfromthefront/brief.md")
print(brief.content)
```

The brief contains: GitHub URL, project goals, known competitors, context notes
added by the owner over time.

### 2. Fetch the GitHub repo summary

Use the GitHub URL from the brief to get the project's README:

```python
import json, urllib.request, urllib.parse

token = secrets.get("cogent/github_token").value
# Convert https://github.com/owner/repo → owner/repo
repo_path = github_url.replace("https://github.com/", "").rstrip("/")
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo_path}/readme",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.raw+json"},
)
with urllib.request.urlopen(req) as r:
    readme = r.read().decode()[:3000]  # first 3000 chars
```

### 3. Derive search queries from the brief

Based on the project description, goals, and known competitors, generate 6–10
search queries. Think about:
- What problem does this project solve? Who else solves it?
- What recent product launches, funding rounds, or blog posts are relevant?
- What are practitioners saying on Twitter about this problem space?
- What new GitHub repos have appeared in this area?

### 4. Run searches across all three backends

```python
import datetime
today = datetime.date.today().isoformat()

findings = []

# Perplexity — general web, news, blog posts
for query in perplexity_queries:
    result = web_search.search(query, recency="day")
    findings.append({"source": "perplexity", "query": query, "result": result.dict()})

# GitHub — new repos and activity in this space
for query in github_queries:
    result = web_search.search_github(query, search_type="repositories")
    findings.append({"source": "github", "query": query, "result": result.dict()})

# Twitter — practitioner discourse and competitor announcements
for query in twitter_queries:
    result = web_search.search_twitter(query, recency="day")
    findings.append({"source": "twitter", "query": query, "result": result.dict()})
```

### 5. Write findings file

```python
import json, uuid

run_id = str(uuid.uuid4())
findings_key = f"newsfromthefront/findings/{today}.md"

content = f"# Findings — {today}\n\nrun_id: {run_id}\n\n"
for f in findings:
    content += f"## {f['source'].upper()}: {f['query']}\n\n"
    content += json.dumps(f['result'], indent=2) + "\n\n"

dir.write(findings_key, content)
print(f"Wrote findings to {findings_key}")
```

### 6. Signal the analyst

```python
channels.send("newsfromthefront:findings-ready", {
    "run_id": run_id,
    "findings_key": findings_key,
    "date": today,
    "is_test": False,
    "is_backfill": False,
})
print("Signalled analyst via newsfromthefront:findings-ready")
```

## Notes

- If the GitHub API is unavailable, skip step 2 and proceed with the cached brief description.
- The brief evolves over time — always re-read it fresh; don't rely on prior context.
- Aim for broad coverage: 3–4 Perplexity queries, 2–3 GitHub queries, 2–3 Twitter queries.
