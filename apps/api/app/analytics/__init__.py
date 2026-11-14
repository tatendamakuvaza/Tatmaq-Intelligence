"""The analysis specification and everything that surrounds a calculation.

    AI agent (or rules)  ->  AnalysisSpec  ->  deterministic execution  ->  verification  ->  interpretation

``spec``          the declarative description of what to compute: the only thing an AI
                  model is allowed to contribute to a calculation
``formatting``    one place that decides how figures are written
``verification``  reconciliation of results against an independent recomputation
"""
