"""Markdown and frontmatter utilities for Komorebi.

提取重複的 frontmatter 操作到共用模組。
"""

from pathlib import Path

import frontmatter


def load_frontmatter(file_path: Path) -> frontmatter.Post:
    """Load a markdown file with frontmatter.

    Args:
        file_path: Path to the markdown file.

    Returns:
        frontmatter.Post object with metadata and content.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If frontmatter is invalid.
    """
    return frontmatter.load(file_path)


def save_frontmatter(file_path: Path, post: frontmatter.Post) -> None:
    """Save a markdown file with frontmatter.

    Args:
        file_path: Path to the markdown file.
        post: frontmatter.Post object to save.
    """
    file_path.write_text(frontmatter.dumps(post), encoding="utf-8")


def read_file_safely(file_path: Path, max_chars: int = 4000) -> str:
    """Read file content with size limit.

    Args:
        file_path: Path to file.
        max_chars: Maximum characters to read.

    Returns:
        File content (truncated if needed) or empty string.
    """
    if not file_path.exists():
        return ""
    try:
        content = file_path.read_text(encoding="utf-8")
        if len(content) > max_chars:
            return content[:max_chars] + "\n...(truncated)"
        return content
    except Exception:
        return ""


def update_section(
    content: str,
    section_name: str,
    new_content: str,
    replace: bool = True,
) -> tuple[str, bool]:
    """Update or insert a markdown section.

    Args:
        content: Full markdown content.
        section_name: Section header (without ##).
        new_content: New content for the section.
        replace: If True, replace existing; if False, append.

    Returns:
        Tuple of (updated content, whether section was found/updated).
    """
    section_header = f"## {section_name}"

    if section_header in content:
        parts = content.split(section_header)
        rest = parts[1]
        # Find the next section
        next_section = rest.find("\n## ")
        if next_section != -1:
            updated = parts[0] + section_header + "\n" + new_content + rest[next_section:]
        else:
            updated = parts[0] + section_header + "\n" + new_content
        return updated, True
    else:
        # Section not found, append at end
        return content + f"\n\n{section_header}\n{new_content}", False


def get_section_content(content: str, section_name: str) -> str | None:
    """Extract content from a specific section.

    Args:
        content: Full markdown content.
        section_name: Section header (without ##).

    Returns:
        Section content or None if not found.
    """
    section_header = f"## {section_name}"

    if section_header not in content:
        return None

    parts = content.split(section_header)
    if len(parts) < 2:
        return None

    rest = parts[1]
    next_section = rest.find("\n## ")
    if next_section != -1:
        return rest[:next_section].strip()
    return rest.strip()
