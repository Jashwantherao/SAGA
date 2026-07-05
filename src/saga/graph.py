"""Builds the SAGA graph:

Studio Director -> Game Designer -> (Asset Maker, Audio Agent) -> Coder <-> QA Agent -> END
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
        return "done"
    if (state.get("retry_count") or 0) >= MAX_RETRIES:
        return "done"
    return "retry"


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("studio_director", studio_director)
    graph.add_node("game_designer", game_designer)
    graph.add_node("asset_maker", asset_maker)
    graph.add_node("audio_agent", audio_agent)
    graph.add_node("coder", coder)
    graph.add_node("qa_agent", qa_agent)

    graph.add_edge(START, "studio_director")
    graph.add_edge("studio_director", "game_designer")
    graph.add_edge("game_designer", "asset_maker")
    graph.add_edge("game_designer", "audio_agent")
    graph.add_edge("asset_maker", "coder")
    graph.add_edge("audio_agent", "coder")
    graph.add_edge("coder", "qa_agent")
    graph.add_conditional_edges("qa_agent", _route_after_qa, {"retry": "coder", "done": END})

    return graph.compile()
