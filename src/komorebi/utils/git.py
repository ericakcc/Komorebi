"""Git utilities for Komorebi.

提取重複的 git 操作到共用模組。
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_git_command(repo_path: Path, args: list[str], timeout: int = 30) -> str:
    """Run a git command asynchronously and return output.

    Args:
        repo_path: Path to the git repository.
        args: Git command arguments.
        timeout: Command timeout in seconds.

    Returns:
        Command output or empty string on error.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        if process.returncode == 0:
            return stdout.decode().strip()
    except asyncio.TimeoutError:
        logger.warning(f"Git command timed out: git {' '.join(args)}")
    except FileNotFoundError:
        logger.warning("Git executable not found")
    except OSError as e:
        logger.warning(f"Git command failed: {e}")
    return ""


async def get_commits_in_range(
    repo_path: Path,
    start_date: datetime,
    end_date: datetime,
) -> list[str]:
    """Collect git commits within a date range.

    Args:
        repo_path: Path to the repository.
        start_date: Start of the range.
        end_date: End of the range.

    Returns:
        List of commit lines (hash + message).
    """
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    log = await run_git_command(
        repo_path,
        ["log", f"--since={start_str}", f"--until={end_str}", "--oneline"],
    )

    return log.split("\n") if log else []


async def get_today_commits(repo_path: Path) -> list[str]:
    """Get today's git commits from a repository.

    Args:
        repo_path: Path to the git repository.

    Returns:
        List of commit messages (short format).
    """
    log = await run_git_command(
        repo_path,
        ["log", "--since=00:00", "--format=%s (%h)", "--no-merges"],
    )
    return log.split("\n") if log else []
