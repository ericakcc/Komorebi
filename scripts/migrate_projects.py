#!/usr/bin/env python3
"""Migrate projects from file mode to folder mode.

Usage:
    uv run python scripts/migrate_projects.py

This script migrates existing project files (data/projects/komorebi.md)
to folder mode (data/projects/komorebi/project.md + tasks.md).

It will:
1. Create a new folder for each project
2. Move the existing .md file to project.md inside the folder
3. Create a tasks.md file with sections extracted from the project
4. Update frontmatter with new fields (type, progress, stats, updated)
"""

import re
import shutil
from datetime import datetime
from pathlib import Path

import frontmatter


def extract_tasks_from_content(content: str) -> tuple[str, str]:
    """Extract task items from project content to create tasks.md.

    Args:
        content: Project markdown content.

    Returns:
        Tuple of (tasks_md_content, remaining_content).
    """
    # Look for task-like items in "開發階段" or similar sections
    tasks_in_progress: list[str] = []
    tasks_pending: list[str] = []
    tasks_completed: list[str] = []

    # Pattern for checkbox items
    checkbox_pattern = re.compile(r"^(\s*)-\s*\[([ xX])\]\s*(.+)$", re.MULTILINE)

    for match in checkbox_pattern.finditer(content):
        checkbox = match.group(2)
        text = match.group(3).strip()

        if checkbox.lower() == "x":
            tasks_completed.append(text)
        else:
            # Determine if in progress or pending based on context
            # For now, put all unchecked as pending
            tasks_pending.append(text)

    # Build tasks.md content
    tasks_lines = []
    if tasks_in_progress:
        tasks_lines.append("## In Progress\n")
        for task in tasks_in_progress:
            tasks_lines.append(f"- [ ] {task}")
        tasks_lines.append("")

    if tasks_pending:
        tasks_lines.append("## Pending\n")
        for task in tasks_pending[:10]:  # Limit to first 10 pending
            tasks_lines.append(f"- [ ] {task}")
        tasks_lines.append("")

    if tasks_completed:
        tasks_lines.append("## Completed\n")
        # Only include recent completed (last 5)
        for task in tasks_completed[-5:]:
            date_str = datetime.now().strftime("%Y-%m-%d")
            tasks_lines.append(f"- [x] {task} ({date_str})")
        tasks_lines.append("")

    tasks_content = "\n".join(tasks_lines) if tasks_lines else """## In Progress

## Pending

## Completed
"""

    return tasks_content, content


def migrate_project(project_file: Path, projects_dir: Path) -> bool:
    """Migrate a single project from file to folder mode.

    Args:
        project_file: Path to the project .md file (e.g., komorebi.md).
        projects_dir: Path to the projects directory.

    Returns:
        True if migration successful, False otherwise.
    """
    project_name = project_file.stem.lower()
    project_folder = projects_dir / project_name

    # Skip if already in folder mode
    if project_folder.exists() and (project_folder / "project.md").exists():
        print(f"  [SKIP] {project_name}: Already in folder mode")
        return False

    print(f"  [MIGRATING] {project_name}...")

    try:
        # Load the project file
        post = frontmatter.load(project_file)

        # Create folder
        project_folder.mkdir(exist_ok=True)

        # Update frontmatter with new fields
        if "type" not in post.metadata:
            post.metadata["type"] = "software"  # Default type
        if "updated" not in post.metadata:
            post.metadata["updated"] = datetime.now().strftime("%Y-%m-%d")
        if "progress" not in post.metadata:
            post.metadata["progress"] = 0
        if "stats" not in post.metadata:
            post.metadata["stats"] = {
                "total_tasks": 0,
                "completed_tasks": 0,
                "commits_this_week": 0,
            }

        # Extract tasks and create tasks.md
        tasks_content, _ = extract_tasks_from_content(post.content)

        # Write project.md
        new_project_path = project_folder / "project.md"
        new_project_path.write_text(frontmatter.dumps(post), encoding="utf-8")

        # Write tasks.md
        tasks_path = project_folder / "tasks.md"
        tasks_path.write_text(tasks_content, encoding="utf-8")

        # Create notes folder
        (project_folder / "notes").mkdir(exist_ok=True)

        # Backup and remove original file
        backup_path = projects_dir / f".backup_{project_name}.md"
        shutil.copy2(project_file, backup_path)
        project_file.unlink()

        print(f"  [OK] {project_name}: Migrated to folder mode")
        print(f"       - Created: {project_folder}/project.md")
        print(f"       - Created: {project_folder}/tasks.md")
        print(f"       - Backup: {backup_path}")
        return True

    except Exception as e:
        print(f"  [ERROR] {project_name}: {e}")
        return False


def main() -> None:
    """Main migration function."""
    # Find projects directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    projects_dir = project_root / "data" / "projects"

    if not projects_dir.exists():
        print(f"Error: Projects directory not found: {projects_dir}")
        return

    print(f"=== Project Migration Tool ===")
    print(f"Projects directory: {projects_dir}")
    print()

    # Find all .md files in projects directory (file mode)
    md_files = list(projects_dir.glob("*.md"))
    # Exclude backup files
    md_files = [f for f in md_files if not f.name.startswith(".backup_")]

    if not md_files:
        print("No projects to migrate (all projects may already be in folder mode)")
        return

    print(f"Found {len(md_files)} project(s) to migrate:")
    for f in md_files:
        print(f"  - {f.name}")
    print()

    # Confirm migration
    response = input("Proceed with migration? [y/N]: ").strip().lower()
    if response != "y":
        print("Migration cancelled.")
        return

    print()
    print("Starting migration...")

    # Migrate each project
    migrated = 0
    for md_file in md_files:
        if migrate_project(md_file, projects_dir):
            migrated += 1

    print()
    print(f"=== Migration Complete ===")
    print(f"Migrated: {migrated}/{len(md_files)} projects")

    # List final structure
    print()
    print("Final structure:")
    for item in projects_dir.iterdir():
        if item.is_dir():
            files = list(item.iterdir())
            print(f"  {item.name}/")
            for f in files:
                print(f"    - {f.name}")


if __name__ == "__main__":
    main()
