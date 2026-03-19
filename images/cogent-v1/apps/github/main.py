# Test: event + data write
channel = event.get("channel_name", "")
data.get("test.txt").write("channel=" + repr(channel))

# Test: file read
scanner_content = file.read("apps/github/scanner/main.md")
if hasattr(scanner_content, 'error'):
    data.get("test.txt").write("channel=" + repr(channel) + "\nscanner_err=" + str(scanner_content.error))
else:
    data.get("test.txt").write("channel=" + repr(channel) + "\nscanner_ok len=" + str(len(scanner_content.content)))

# Test: repos.md
repos_content = data.get("repos.md").read()
if hasattr(repos_content, 'error'):
    data.get("test.txt").write("channel=" + repr(channel) + "\nscanner_ok\nrepos_err=" + str(repos_content.error))
else:
    data.get("test.txt").write("channel=" + repr(channel) + "\nscanner_ok\nrepos_ok len=" + str(len(repos_content.content)))

# Test: github API
org_repos = github.list_org_repos("metta-ai", limit=3)
if hasattr(org_repos, 'error'):
    data.get("test.txt").write("channel=" + repr(channel) + "\nscanner_ok\nrepos_ok\ngithub_err=" + org_repos.error)
else:
    names = [r.full_name for r in org_repos]
    data.get("test.txt").write("channel=" + repr(channel) + "\nscanner_ok\nrepos_ok\ngithub_ok repos=" + str(names))

data.get("last_scan.txt").write("done")
