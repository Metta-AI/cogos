# Pointy Configuration

## Asana

- **workspace_id**: 1209016784099267
- **project_id**: 1213471594342425
- **project_name**: Thread Roadmap

## GitHub

- **org**: Metta-AI

## Google Drive

- **reports_folder_id**: 1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq
- **report_name_format**: Daily Thread Update — YYYY-MM-DD

## Discord

- **channel_id**: 1483962779336446114

## Team Mappings

Team mappings (Asana name → GitHub login) are loaded at runtime from the secret
`cogent/{cogent}/pointy_team_mappings`. The secret should be a JSON object:

```json
{"Asana Display Name": "github_login", ...}
```
