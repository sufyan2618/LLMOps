from evaluation.judges import contains_match, llm_judge_heuristic


def test_contains_match_positive():
    score = contains_match(input="q", output="The capital is Paris.", expected_output="Paris")
    assert score["value"] == 1.0


def test_contains_match_negative():
    score = contains_match(input="q", output="I don't know", expected_output="Paris")
    assert score["value"] == 0.0


def test_judge_empty():
    score = llm_judge_heuristic(input="q", output="")
    assert score["value"] == 0.0
