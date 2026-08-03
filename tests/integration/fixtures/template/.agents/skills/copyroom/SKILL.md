---
name: copyroom
description: Fixture skill proving skills ship verbatim (not rendered) — literal {{ }} must survive.
auto_trigger:
  keywords: ["fixture"]
---

# Fixture skill

Rename files to `*.jinja` and use `{{ project_name }}` like
`{{ project_name | lower }}` — these braces must survive generation untouched.
