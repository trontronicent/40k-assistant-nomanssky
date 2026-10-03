---
title: About the Example Lore library
tags: [example, plugin]
---

# About the Example Lore library

This library is installed by the **Example STC** plugin. It shows how a plugin
ships Codex documents:

- Every Markdown file under `codex/Example Lore/` becomes one Codex document.
- A subfolder becomes the document's category (see *Forge Worlds/Mars.md*).
- Optional YAML front matter sets `title`, `category` and `tags`.
- Files and folders whose names start with `_` or `.` are skipped.

The documents are read-only inside the app. To change one, copy it into your
own Codex folder.
