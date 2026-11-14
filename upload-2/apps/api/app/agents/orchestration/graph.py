"""The two workflows, as LangGraph state graphs (specification section 7.3).

``build_analysis_graph``   plan, verify the file, validate the data against the plan,
                           calculate, reconcile, report. Extends the specification's
                           first sequential graph with the Chief's planning step,
                           conditional routing and the two correction loops.
``build_ingestion_graph``  import and profile an upload, then clean it.

Retries and resumption are handled per task in ``tasks.py``, backed by PostgreSQL,
rather than by a LangGraph checkpointer: the database is already the durable record.
"""

from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from . import routing
from .nodes import WorkflowNodes
from .state import AnalysisState

#: Upper bound on steps in one run: the longest path (with both loops taken) is 13.
RECURSION_LIMIT = 25


def build_analysis_graph(nodes: WorkflowNodes):
    graph = StateGraph(AnalysisState)
    graph.add_node("preflight", nodes.preflight)
    graph.add_node("planning", nodes.planning)
    graph.add_node("acquisition", nodes.acquisition)
    graph.add_node("cleaning", nodes.cleaning)
    graph.add_node("statistics", nodes.statistics)
    graph.add_node("verification", nodes.verification)
    graph.add_node("reporting", nodes.reporting)
    graph.add_node("finalise", nodes.finalise)

    graph.add_edge(START, "preflight")
    graph.add_conditional_edges("preflight", routing.after_preflight, ["planning", "finalise"])
    graph.add_conditional_edges("planning", routing.after_planning, ["acquisition", "finalise"])
    graph.add_conditional_edges("acquisition", routing.after_acquisition, ["cleaning", "finalise"])
    graph.add_conditional_edges("cleaning", routing.after_cleaning, ["statistics", "planning", "finalise"])
    graph.add_conditional_edges("statistics", routing.after_statistics, ["verification", "finalise"])
    graph.add_conditional_edges("verification", routing.after_verification, ["reporting", "statistics", "finalise"])
    graph.add_edge("reporting", "finalise")
    graph.add_edge("finalise", END)
    return graph.compile()


def build_ingestion_graph(nodes: WorkflowNodes):
    graph = StateGraph(AnalysisState)
    graph.add_node("preflight", nodes.ingest_preflight)
    graph.add_node("acquisition", nodes.ingest_acquire)
    graph.add_node("cleaning", nodes.ingest_clean)
    graph.add_node("finalise", nodes.ingest_finalise)

    graph.add_edge(START, "preflight")
    graph.add_conditional_edges("preflight", partial(routing.after_ingest_step, next_step="acquisition"),
                                ["acquisition", "finalise"])  # fmt: skip
    graph.add_conditional_edges("acquisition", partial(routing.after_ingest_step, next_step="cleaning"),
                                ["cleaning", "finalise"])  # fmt: skip
    graph.add_edge("cleaning", "finalise")
    graph.add_edge("finalise", END)
    return graph.compile()
