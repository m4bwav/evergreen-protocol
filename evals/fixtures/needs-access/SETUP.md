# Setup: orders-report

What [SKILL.md](SKILL.md) needs.

## Needs

| id | kind | check | for | if missing |
|---|---|---|---|---|
| orders-db | access | `python -c "import sys; sys.stderr.write('ERROR: permission denied for table orders'); sys.exit(1)"` | reading the orders table for the weekly report | required |
