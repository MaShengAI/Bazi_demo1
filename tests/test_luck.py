from app.domain.luck.calculator import _age_parts, determine_direction


def test_direction_rules() -> None:
    assert determine_direction("甲", "male").direction == "forward"
    assert determine_direction("乙", "female").direction == "forward"
    assert determine_direction("乙", "male").direction == "backward"
    assert determine_direction("甲", "female").direction == "backward"


def test_start_age_exact_ratios() -> None:
    assert _age_parts(3 * 86400)["years"] == 1
    assert _age_parts(86400)["months"] == 4
    assert _age_parts(3600)["days"] == 5
