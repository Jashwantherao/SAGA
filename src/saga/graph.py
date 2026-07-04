"""Builds the Week 1 SAGA graph: Studio Director -> Game Designer."""

from langgraph.graph import END, START, StateGraph

from saga.agents.game_designer import game_designer
from saga.agents.studio_director import studio_director
from saga.state import GraphState


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("studio_director", studio_director)
    graph.add_node("game_designer", game_designer)

    graph.add_edge(START, "studio_director")
    graph.add_edge("studio_director", "game_designer")
    graph.add_edge("game_designer", END)

    return graph.compile()
