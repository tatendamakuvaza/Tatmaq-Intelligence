"""The five MVP agents and the orchestration that connects them.

Agents never touch the database. Each receives a typed task and a toolbox limited to
what that agent is permitted to use, and returns a structured, validated result. The
orchestration layer records what happened.
"""
