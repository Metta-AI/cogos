# GitHub cog orchestrator — Python executor
# Dispatches hourly/daily scans and on-demand discovery to LLM coglets.

channel = event.get("channel_name", "")
payload = event.get("payload", {})

# Source repo identity
SOURCE_REPO = "metta-ai/cogents-v1"

# Read coglet prompts
scanner_content = file.read("apps/github/scanner/main.md")
if hasattr(scanner_content, 'error'):
    print("github: scanner prompt not found: " + str(scanner_content.error))
    exit()
discovery_content = file.read("apps/github/discovery/main.md")
if hasattr(discovery_content, 'error'):
    print("github: discovery prompt not found: " + str(discovery_content.error))
    exit()

# Create coglets
scanner = cog.make_coglet("scanner", entrypoint="main.md",
    files={"main.md": scanner_content.content})
discovery = cog.make_coglet("discovery", entrypoint="main.md",
    files={"main.md": discovery_content.content})

worker_caps = {
    "github": None, "data": None, "dir": None,
    "file": None, "channels": None, "stdlib": None,
}

if channel == "github:discover":
    # On-demand discovery
    repo = payload.get("repo", "")
    if not repo:
        print("github: discover missing repo in payload")
        exit()
    run = coglet_runtime.run(discovery, procs, capability_overrides=worker_caps)
    run.process().send({"repo": repo})

elif channel == "system:tick:hour" or not channel:
    # Check if daily scan is due
    last_scan = data.get("last_scan.txt").read()
    today = stdlib.time.strftime("%Y-%m-%d")
    if not hasattr(last_scan, 'error') and last_scan.content.strip() == today:
        print("github: already scanned today")
        exit()

    # Read repos.md and build scan list
    repos_content = data.get("repos.md").read()
    if hasattr(repos_content, 'error'):
        print("github: repos.md not found")
        exit()

    scan_repos = []
    for line in repos_content.content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("/*"):
            # Org wildcard — list org repos
            org = line[:-2]
            org_repos = github.list_org_repos(org, limit=100)
            if hasattr(org_repos, 'error'):
                print("WARN: list_org_repos " + org + " failed: " + org_repos.error)
                continue
            for r in org_repos:
                scan_repos.append(r.full_name)
        else:
            scan_repos.append(line)

    # Deduplicate
    scan_repos = list(dict.fromkeys(scan_repos))

    # Spawn scanner coglet for each repo
    for repo in scan_repos:
        is_self = repo == SOURCE_REPO
        run = coglet_runtime.run(scanner, procs, capability_overrides=worker_caps)
        run.process().send({"repo": repo, "is_self_repo": is_self})

    # Mark today as scanned
    data.get("last_scan.txt").write(today)
    print("github: dispatched " + str(len(scan_repos)) + " scans")

else:
    print("github: unknown channel " + repr(channel))
