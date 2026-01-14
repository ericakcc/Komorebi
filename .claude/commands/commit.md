---
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git add:*), Bash(git commit:*), Read, Edit
description: Smart commit - auto add appropriate files and create conventional commit
---

## Context

All changes (staged + unstaged + untracked):
!`git status`

Current .gitignore:
!`cat .gitignore 2>/dev/null || echo "No .gitignore found"`

Recent commits (for style reference):
!`git log --oneline -5`

## Task

Intelligently add files and create a commit using Conventional Commits format.

### Step 1: Analyze Changes

Review all modified and untracked files. Categorize them:

**Should ADD:**
- Source code (.py, .ts, .js, etc.)
- Config files (pyproject.toml, package.json, etc.)
- Documentation (.md files if intentionally created)
- Test files

**Should SKIP (and suggest .gitignore):**
- Generated files: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `dist/`, `build/`
- Dependencies: `node_modules/`, `.venv/`, `venv/`
- IDE/Editor: `.idea/`, `.vscode/settings.json`, `*.swp`
- Secrets: `.env`, `*.key`, `credentials.*`, `secrets.*`
- OS files: `.DS_Store`, `Thumbs.db`
- Large binary files, logs

### Step 2: Update .gitignore (if needed)

If you find files that should be ignored but aren't in .gitignore, suggest adding them.

### Step 3: Stage Files

Run `git add` for appropriate files only.

### Step 4: Create Commit

Format:
```
<type>(<scope>): <description>

Co-Authored-By: Claude <noreply@anthropic.com>
```

Types: feat, fix, docs, refactor, test, chore
Scope: api, core, config, tests
