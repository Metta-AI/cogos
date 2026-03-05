---
name: review-github-prs
program_name: hello
description: Review open pull requests and post summary comments
tools:
  - memory get
  - memory put
  - event send
memory_keys:
  - identity
  - github-repos
priority: 8.0
runner: ecs
resources:
  - ecs
---
Review all open pull requests on the configured GitHub repositories.
For each PR, read the diff and existing comments, then post a summary
review comment with suggestions and risk assessment.
