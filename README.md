# Example STC — Strategicum plugin template

A plugin (**STC**) for the [40k Assistant / Strategicum](https://github.com/trontronicent/40k-assistant).
Install it from the app's **STC Archive** page once it is listed in the
[STC Index](https://github.com/trontronicent/40k-assistant-plugins).

## What it adds

| Kind | Item | Shown in the app as |
|---|---|---|
| Theme | Ember Forge | `example-stc--ember-forge` in the theme selector |
| Persona | Lexicanum Adept | a persona with an *STC* badge, answering from the Example Lore library |
| Codex | Example Lore (2 documents) | a read-only Codex library |

## Making your own plugin from this template

1. *Use this template* on GitHub, clone your new repository.
2. In `strategicum-plugin.json` change `id` (unique, lowercase, never reused),
   `name`, `description`, `author`, and list what you contribute. Remove the
   kinds you do not use, and their folders.
3. Validate:

   ```
   curl -fsSLO https://raw.githubusercontent.com/trontronicent/40k-assistant-plugins/main/tools/registry_tool.py
   python registry_tool.py manifest .
   ```

4. Release: set `version`, commit, `git tag v<version>`, `git push --tags`.
5. Submit it to the index (see the registry's CONTRIBUTING.md).

## Layout

```
strategicum-plugin.json         manifest (required)
themes/<id>/theme.json          displayName, description, author, version, isMobileCompatible
themes/<id>/theme.css           :root custom properties only; nothing loaded from the internet
themes/<id>/preview.png         optional, 300x180
personas/<id>.json              persona fields (below)
codex/<Library>/**/*.md         Markdown; subfolders = categories; front matter title/category/tags
```

### Persona fields

`name` and `system_prompt` are required. Allowed besides: `appearance`,
`clothing`, `personality`, `speech_style`, `background`, `custom`,
`system_prompt_locked`, `model` (`""` = whatever model the user has selected —
recommended, since you cannot know which models a user has), `voice`,
`temperature`, `repeat_penalty`, `top_p`, `top_k`, `roleplay_helpers`,
`mnemo_vigil_threshold_hours`, `web_search_mode` (`off`/`tool`/`auto`),
`knowledge_mode` (`off`/`tool`/`auto`), `knowledge_top_k` (1–10),
`knowledge_all_libraries`, `create_memories`, `read_memories`, and
`knowledge_plugin_libraries` — names of Codex libraries **this plugin**
contributes; the app links them to the persona on install. Any other key is
dropped.

## License

MIT, see [LICENSE](LICENSE).
