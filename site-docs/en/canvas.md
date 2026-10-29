# Canvas courses & assignments

Auth: **personal token first** (settable/clearable in the web Settings page, or `WESTLAKE_CANVAS_TOKEN`), falling back to the unified-password session automatically. On a 401, suspect a stale token: `westlake setup --clear-canvas-token`.

## Read queries

```bash
westlake canvas courses                    # course list
westlake canvas deadlines                  # all deadlines (no 7-day cap)
westlake canvas exams                      # exams & quizzes
westlake canvas todo                       # to-dos
westlake canvas assignment-info --course <x> --assignment <y> \
       [--download ./dir]                  # details + attachments + rubric
westlake canvas files --course ...         # course files (downloadable)
westlake canvas discussions|announcements|inbox
```

## Three write ops (consequence gate)

```bash
westlake canvas submit --course ... --assignment ... --file hw.pdf --dry-run   # 1) plan
westlake canvas submit ... --yes                                            # 2) submit
westlake canvas submission --course ... --assignment ...                     # 3) read back
westlake canvas reply  --course ... --topic ... --text "..." --yes           # discussion reply
westlake canvas send   --conversation 123 --text "..." --yes                 # inbox message
```

Without `--yes` a structured risk descriptor prints (what changes / risk / severity / reversibility) and the command exits 1; conversations marked `cannot_reply` are refused outright. Recommended flow for submissions: plan → `--yes` → read back.
