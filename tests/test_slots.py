import pytest

from crabfit_mcp.slots import expand_times, validate_times


def test_leap_date_and_ordered_deduplication():
    assert validate_times(["2359-29022024", "0900-20102026", "2359-29022024"], allow_empty=False) == ["2359-29022024", "0900-20102026"]


@pytest.mark.parametrize("times", [
    ["0900-29022025"], ["2400-20102026"], ["0960-2"],
    ["0900-8"], ["0900-00012026"], ["0900-20102026", "0900-2"],
    ["９000-2"], ["0900-2\n"], [],
])
def test_invalid_slots(times):
    with pytest.raises(ValueError):
        validate_times(times, allow_empty=False)


def test_expansion_replaces_minutes_and_deduplicates():
    expected = ["0900-20102026", "0915-20102026", "0930-20102026", "0945-20102026"]
    assert expand_times(["0900-20102026"]) == expected
    assert expand_times(["0959-20102026", "0915-20102026"]) == expected
    assert expand_times(["2359-0"]) == ["2300-0", "2315-0", "2330-0", "2345-0"]
    assert validate_times([], allow_empty=True) == []
