# Agents

All five implement one interface (`agents/base/agent.py`): receive a typed `AgentTask`, return a
validated `AgentResult`. Agents never touch the database; the orchestration layer records their work.
An agent reaches the outside world only through its `Toolbox`, which holds exactly the tools
`agents/base/permissions.py` grants it.

| # | Agent | Actions | Tools it is granted | Uses an AI model |
| --- | --- | --- | --- | --- |
| 01 | Chief Intelligence | `plan_analysis` | `llm` | optional |
| 02 | Data Acquisition | `import_and_profile`, `verify_and_load` | `original_file.read`, `dataset.write_raw` | never |
| 03 | Data Cleaning | `clean_and_validate`, `validate_for_analysis` | `dataset.read_raw`, `dataset.write_cleaned`, `dataset.read_cleaned` | never |
| 04 | Statistical Analysis | `run_analysis` | `dataset.read_cleaned` | never |
| 05 | Report Generation | `generate_report` | `llm`, `artifact.write` | optional |

What the grants guarantee: the agent that calculates has no AI model; the two agents that may use one
cannot read datasets; nothing can write an original file.

## When they run

**On upload** (ingestion job): Acquisition imports the file, finds the header and worksheet, types
each column, recognises business roles (date, sales amount, cost, product, branch...), fingerprints
the file and stores the table as imported. Cleaning then standardises dates, numbers and spellings,
flags duplicates, gaps and unusual values, and stores the cleaned table with a log of every change.

**On each question** (analysis job): the Chief plans; Acquisition re-computes the file's fingerprint
to prove it is unchanged; Cleaning checks the cleaned data can support each planned operation;
Statistical Analysis calculates; Quality Verification reconciles; Report Generation writes the files.

## Things worth knowing

- **Dates.** `01/09/2026` is read as 1 September. If any date in the column settles the order
  (`25/09/2026`), that decides it; otherwise the organisation's default applies and the number of
  dates that rested on the assumption is reported.
- **Currencies.** A dataset with a currency column holding more than one currency is analysed once
  per currency. Amounts in different currencies are never added.
- **Missing values** are never treated as zero. A row without a cost is left out of profit figures
  and counted in the report.
- **Duplicates** are flagged and stay in the totals, with their sales value stated.
- **TOTAL lines** at the foot of a spreadsheet are set aside so they are not double-counted.
- **Incomplete months** (an export taken mid-month) are excluded from month comparisons and trends.
- **Trends** are only called upward or downward when statistically significant at the 5% level.
- **Unusual values** are flagged for review and never described as errors or wrongdoing.

## Adding an analysis

1. Add an operation model to `analytics/spec.py` and its column requirements to `required_columns`.
2. Put the mathematics in `packages/analytics-core` with tests against hand-worked answers.
3. Add a handler in `agents/statistical_analysis/` that turns results into findings with evidence,
   and register it in `HANDLERS`.
4. Teach `chief_intelligence/planner.py` when to choose it, and describe it in `prompts.py`.
5. If it reports money, add reconciliation checks to `analytics/verification.py`.

## Adding an agent

Add a descriptor to `agents/base/registry.py`, grant its tools in `permissions.py`, implement
`BaseAgent`, and add a step in `orchestration/nodes.py` and `graph.py`.
