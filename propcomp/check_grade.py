from propcomp.grade import grade_number, grade_prop, minutes_to_seconds, parse_line
from propcomp.signals import check as check_signals


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    check(parse_line("19+") == 19, "milestone parse")
    check(parse_line("18.5") == 18.5, "total parse")
    check(grade_number(31, 18.5, "ou") == "over", "over")
    check(grade_number(18, 18.5, "ou") == "under", "under")
    check(grade_number(18, 18, "ou") == "push", "push")
    check(grade_number(19, 19, "milestone") == "yes", "milestone hit")
    check(grade_number(18, 19, "milestone") == "no", "milestone miss")
    check(minutes_to_seconds("34") == 2040, "whole minutes")
    check(minutes_to_seconds("0:12") == 12, "clock minutes")

    played = {
        "played": True,
        "player_id": "1",
        "team_id": "10",
        "pts": 22,
        "reb": 11,
        "ast": 10,
        "stl": 1,
        "blk": 0,
        "fg3m": 3,
        "tov": 2,
        "quarters": {1: {"pts": 8, "reb": 2, "ast": 1, "stl": 0, "blk": 0, "fg3m": 1, "tov": 0}},
    }
    context = {"first_basket": "1", "first_team_fg": {"10": "1"}}
    result, actual = grade_prop(
        {"market": "Total Points", "kind": "ou", "line_num": 18.5},
        played,
        context,
    )
    check(result == "over" and actual == 22, "points grade")
    result, _actual = grade_prop(
        {"market": "To Record a Double Double", "kind": "yesno", "line_num": None},
        played,
        context,
    )
    check(result == "yes", "double double")
    result, _actual = grade_prop(
        {"market": "To Record a Triple Double", "kind": "yesno", "line_num": None},
        played,
        context,
    )
    check(result == "yes", "triple double")
    result, _actual = grade_prop(
        {"market": "First Basket", "kind": "yesno", "line_num": None},
        played,
        context,
    )
    check(result == "yes", "first basket")
    result, actual = grade_prop(
        {"market": "Points Milestones - 1st Quarter", "kind": "milestone", "line_num": 5},
        played,
        context,
    )
    check(result == "yes" and actual == 8, "quarter points")
    result, _actual = grade_prop(
        {"market": "Total Points", "kind": "ou", "line_num": 10},
        {"played": False, "player_id": "1"},
        context,
    )
    check(result == "void", "did not play")
    check_signals()
    print("grade checks passed")


if __name__ == "__main__":
    main()
