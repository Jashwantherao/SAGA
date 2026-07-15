"""Builds the SAGA graph:

Studio Director -> Game Designer -> (Asset Maker, Audio Agent)
    -> Coder <-> QA Agent (per level, advancing through the design doc's
       levels via advance_level) -> END
"""

from langgraph.graph import END, START, StateGraph

from saga.agents.asset_maker import asset_maker
from saga.agents.audio_agent import audio_agent
from saga.agents.coder import coder
from saga.agents.game_designer import game_designer
from saga.agents.qa_agent import qa_agent
from saga.agents.studio_director import studio_director
from saga.state import GraphState

MAX_RETRIES = 6


def _route_after_qa(state: GraphState) -> str:
    if state.get("qa_passed"):
        design_doc = state.get("design_doc") or {}
        total_levels = len(design_doc.get("levels") or [None])
        if (state.get("current_level") or 0) + 1 < total_levels:
            return "next_level"
        return "done"
    if (state.get("retry_count") or 0) >= MAX_RETRIES:
        return "done"
    return "retry"


def advance_level(state: GraphState) -> GraphState:
    """Move the Coder<->QA loop to the design doc's next level, with a fresh
    retry budget."""
    next_level = (state.get("current_level") or 0) + 1
    print(f"[Graph] Level {next_level + 1} up next")
    return {"current_level": next_level, "qa_errors": None, "retry_count": 0}


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("studio_director", studio_director)
    graph.add_node("game_designer", game_designer)
    graph.add_node("asset_maker", asset_maker)
    graph.add_node("audio_agent", audio_agent)
    graph.add_node("coder", coder)
    graph.add_node("qa_agent", qa_agent)
    graph.add_node("advance_level", advance_level)

    graph.add_edge(START, "studio_director")
    graph.add_edge("studio_director", "game_designer")
    graph.add_edge("game_designer", "asset_maker")
    graph.add_edge("game_designer", "audio_agent")
    graph.add_edge("asset_maker", "coder")
    graph.add_edge("audio_agent", "coder")
    graph.add_edge("coder", "qa_agent")
    graph.add_conditional_edges(
        "qa_agent",
        _route_after_qa,
        {"retry": "coder", "next_level": "advance_level", "done": END},
    )
    graph.add_edge("advance_level", "coder")

    return graph.compile()
