# GitHub cog orchestrator — Python executor
# Dispatches hourly/daily scans and on-demand discovery to LLM coglets.

channel = event.get("channel_name", "")
payload = event.get("payload", {})

# Source repo identity
SOURCE_REPO = "metta-ai/cogents-v1"

worker_caps = {
    "github": None, "disk": disk,
    "channels": None, "stdlib": None,
}

def _make_scanner():
    content = src.get("scanner/main.md").read()
    if hasattr(content, 'error'):
        print("github: scanner prompt not found: " + str(content.error))
        return None
    return cog.make_coglet("scanner", entrypoint="main.md",
        files={"main.md": content.content})

def _make_discovery():
    content = src.get("discovery/main.md").read()
    if hasattr(content, 'error'):
        print("github: discovery prompt not found: " + str(content.error))
        return None
    return cog.make_coglet("discovery", entrypoint="main.md",
        files={"main.md": content.content})

if channel == "github:discover":
    # On-demand discovery
    repo = payload.get("repo", "")
    if not repo:
        print("github: discover missing repo in payload")
        exit()
    discovery = _make_discovery()
    if discovery is None:
        exit()
    run = coglet_runtime.run(discovery, procs, capability_overrides=worker_caps)
    run.process().send({"repo": repo})

elif channel == "system:tick:hour" or not channel:
    # Check if daily scan is due
    last_scan = disk.get("last_scan.txt").read()
    today = stdlib.time.strftime("%Y-%m-%d")
    if not hasattr(last_scan, 'error') and last_scan.content.strip() == today:
        print("github: already scanned today")
        exit()

    # Read repos.md and build scan list
    repos_content = disk.get("repos.md").read()
    if hasattr(repos_content, 'error'):
        print("github: repos.md not found")
        exit()

    scan_repos = []
    for line in repos_content.content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("/*"):
            org = line[:-2]
            org_repos = github.list_org_repos(org, limit=100)
            if hasattr(org_repos, 'error'):
                print("WARN: list_org_repos " + org + " failed: " + org_repos.error)
                continue
            for r in org_repos:
                scan_repos.append(r.full_name)
        else:
            scan_repos.append(line)

    scan_repos = list(dict.fromkeys(scan_repos))

    if scan_repos:
        scanner = _make_scanner()
        if scanner is not None:
            for repo in scan_repos:
                is_self = repo == SOURCE_REPO
                run = coglet_runtime.run(scanner, procs, capability_overrides=worker_caps)
                run.process().send({"repo": repo, "is_self_repo": is_self})

    disk.get("last_scan.txt").write(today)
    print("github: dispatched " + str(len(scan_repos)) + " scans")

else:
    print("github: unknown channel " + repr(channel))
