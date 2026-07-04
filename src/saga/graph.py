"""Builds the SAGA graph: Studio Director -> Game Designer -> (Asset Maker, Audio Agent)."""

from langgraph.graph import END, START, StateGraph

from saga.agents.asset_maker import asset_maker
from saga.agents.audio_agent import audio_agent
from saga.agents.game_designer import game_designer
from saga.agents.studio_director import studio_director
from saga.state import GraphState


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("studio_director", studio_director)
    graph.add_node("game_designer", game_designer)
    graph.add_node("asset_maker", asset_maker)
    graph.add_node("audio_agent", audio_agent)

    graph.add_edge(START, "studio_director")
    graph.add_edge("studio_director", "game_designer")
    graph.add_edge("game_designer", "asset_maker")
    graph.add_edge("game_designer", "audio_agent")
    graph.add_edge("asset_maker", END)
    graph.add_edge("audio_agent", END)

    return graph.compile()
