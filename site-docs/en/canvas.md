# Canvas Courses & Assignments

Authentication uses a **personal access token by default** (configurable and removable in the web Settings UI or via `WESTLAKE_CANVAS_TOKEN`), gracefully falling back to your unified campus session if no token is provided. If you encounter HTTP 401 Unauthorized errors, your token may have expired: run `westlake setup --clear-canvas-token` to reset it.

## Read-Only Queries

```bash
westlake canvas courses                    # active course list
westlake canvas deadlines                  # complete upcoming deadlines (bypasses default 7-day cap)
westlake canvas exams                      # quizzes and scheduled exams
westlake canvas todo                       # Canvas to-do items
westlake canvas assignment-info --course <x> --assignment <y> \
       [--download ./dir]                  # assignment brief, rubric, and attached files
westlake canvas files --course ...         # browse and download course file repositories
westlake canvas discussions|announcements|inbox
```

## Write Operations & Consequence Gate

```bash
westlake canvas submit --course ... --assignment ... --file hw.pdf --dry-run   # 1) Pre-flight simulation
westlake canvas submit ... --yes                                            # 2) Execute submission
westlake canvas submission --course ... --assignment ...                     # 3) Verify submitted artifact
westlake canvas reply  --course ... --topic ... --text "..." --yes           # Post discussion reply
westlake canvas send   --conversation 123 --text "..." --yes                 # Send inbox message
```

Every write operation is protected by the consequence gate. Omitting `--yes` prints a structured risk descriptor (action target, risk category, severity level, and reversibility) and aborts execution with exit code 1. Conversations flagged with `cannot_reply` are automatically rejected. The standard protocol for assignment submission is: **simulate (`--dry-run`) → execute (`--yes`) → verify (`submission`)**.
