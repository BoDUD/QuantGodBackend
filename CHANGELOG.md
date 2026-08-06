# Changelog

All notable repository changes should be summarized here.

## Unreleased

- Added repository governance files for the QuantGod split repository workspace.
- Added a stdlib-only governance checker and GitHub Actions workflow.
- Added dry-run-first, bounded disk-pressure maintenance for allow-listed Backend,
  active MT5 runtime, and private status artifacts, plus a sanitized operator
  overview summary of its latest result.
- Hardened runtime log and JSONL maintenance against symlink, hardlink, ownership,
  and path-swap races with descriptor-based identity checks before mutation.

## Notes

Use concise entries grouped by feature, fix, documentation, infrastructure, and security where appropriate.
