"""Studio Director — orchestrator entry point.

Week 1 scope: a thin pass-through node that receives the one-line game idea
and initializes shared state. Routing/retry logic (Coder<->QA loop, human
review gate) is out of scope until later phases of the roadmap.
"""

from saga.state import GraphState


def studio_director(state: GraphState) -> GraphState:
    print(f"[Studio Director] Received prompt: {state['user_prompt']!r}")
    return {"user_prompt": state["user_prompt"], "design_doc": None}
