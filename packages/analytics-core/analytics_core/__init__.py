"""TATMAQ analytics core.

Every number that reaches a customer is calculated here, by ordinary deterministic
Python. Nothing in this package talks to a database, a file store, a network or an
AI model, which is what makes it possible to test each calculation against answers
worked out independently.

Sub-packages
------------
cleaning     parsing and standardising numbers, dates and text; duplicate detection
statistics   descriptive statistics, correlation, regression, trends, outliers
financial    exact decimal money arithmetic, sales and profitability summaries
validation   reconciliation checks that results must pass before they are reported
"""

__version__ = "0.1.0"
