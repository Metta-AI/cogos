# Standup Brief

## Asana

- **workspace_id**: 1209016784099267
- **project_id**: 1213471594342425
- **project_name**: Thread Roadmap
- **sprint_section_id**: 1213471596632101
- **sprint_section_name**: March 2026

## GitHub Repos

- metta-ai/metta
- metta-ai/cogos
- metta-ai/cogents-v1

## Team Members

Map of GitHub login -> Asana display name. Update this as people join/leave.

| GitHub Login         | Asana Name               |
|----------------------|--------------------------|
| daveey               | David Bloomin            |
| nishu-builder        | Nishad Singh             |
| alexsmith            | Alex Smith               |
| subhojeet            | Subhojeet Pramanik       |
| rhiggins             | Richard Higgins          |
| malcolmocean         | Malcolm Ocean            |
| Agentic-Andre        | Andre von Houck          |
| yatharth             | Yatharth Agarwal         |
| martinhess           | Martin Hess              |
| axelkerbec           | Axel Kerbec              |
| noahfarr             | Noah Farr                |
| alexvardakostas      | Alexandros Vardakostas   |

NOTE: GitHub logins marked above are guesses except daveey and nishu-builder
(confirmed from git history). Update these as the bot encounters real logins.

## Discord

- **channel_id**: 1483962779336446114

## Output Format

Post two views in each standup:

### View 1: Per-Thread

For each thread (Asana task) in the sprint section, list contributors and their
commit counts per repo. Omit any thread/person/repo combo with zero commits.

```
## By Thread

### Autocurricula
- Axel Kerbec: metta (5), cogos (2)
- Noah Farr: metta (3)

### LLMs play CvC
- Richard Higgins: metta (8)

### Cogent: V1 - First Contact
- Nishad Singh: cogents-v1 (4), cogos (1)
```

### View 2: Per-Person

Same data, regrouped by person first, then threads underneath.

```
## By Person

### Axel Kerbec
- Autocurricula: metta (5), cogos (2)

### Richard Higgins
- LLMs play CvC: metta (8)

### Nishad Singh
- Cogent: V1 - First Contact: cogents-v1 (4), cogos (1)
```

## Matching Commits to Threads

To associate a commit with a thread, use the LLM to judge whether the commit
message (and optionally PR title/description) relates to the thread's topic.
A commit can match multiple threads if the work spans them. If a commit doesn't
clearly match any thread, group it under "Untracked" at the bottom.
