---
description: Move or relocate files/directories in this project, with mandatory review before any git commit
---

When moving, relocating, or reorganizing files or directories in this project:

1. Show me the full plan before executing anything (source path, destination path, what happens to any existing git history at the destination).
2. If the destination path already contains something unexpected, stop and ask, don't assume it's safe to overwrite or move aside without confirming what it actually is first.
3. After moving, run the project's normal verification (tests, tsc --noEmit, or equivalent for whatever was moved) to confirm nothing broke.
4. Do NOT run git add or git commit at any point in this process, regardless of how clean the change looks. Stop after verification and report what's ready to be committed, staged or unstaged, your choice, but the commit itself is mine to run.
