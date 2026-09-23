<!-- CODEOWNER SUMMARY -->
## 📋 Code Owner Summary

This PR modifies **{{ .file_count }}** file{{if gt .file_count 1}}s{{end}}.

Each section below groups changed files by the owners from `CODEOWNERS`. Approval is required from one listed owner for each required owner group.

Legend: ✅ approval acquired, 🟠 approval still required.

{{range .owner_groups}}
### {{if .approval_marker}}{{.approval_marker}} {{end}}{{.owners}}
{{range .files}}- `{{.path}}`
{{end}}
{{end}}
---
*This comment is automatically [generated and updated]({{.github_run_url}}) when files or reviews change.*
