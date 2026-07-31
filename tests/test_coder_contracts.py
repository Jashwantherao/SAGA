from saga.agents.coder_contracts import TEMPLATE_CONTRACTS


def test_maze_chase_contract_exposes_objective_qa_adapters():
    descriptions = " ".join(
        description for description, _pattern in TEMPLATE_CONTRACTS["maze_chase"]
    )

    assert "stable player handle" in descriptions
    assert "stable wall array" in descriptions
    assert "pickup total" in descriptions
    assert "state" in descriptions
    assert "stable patroller handle" in descriptions
