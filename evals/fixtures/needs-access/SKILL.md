---
name: orders-report
description: "Weekly orders report from the orders database. Use when the user asks for the orders report."
---

# Orders report

Fixture skill for the evergreen eval suite (case action-4). Needs read access to the orders database; see [SETUP.md](SETUP.md).

## Step 1

Query `orders` for the requested week and write `report.md` with the count and total per day.
