import pytest
from .filters import FilterGroup, FilterOperator, PropertyFilter, parse_filters


def test_parse_filters_none():
    """Test that None input returns None."""
    assert parse_filters(None) is None


def test_parse_filters_empty_string():
    """Test that an empty string returns None (as it's not a valid filter string)."""
    assert parse_filters("") is None


def test_parse_filters_invalid_string_raises_error():
    """Test that an invalid filter string raises a ValueError."""
    with pytest.raises(ValueError):
        parse_filters("invalid-filter")


def test_parse_filters_single_string():
    """Test parsing a single filter string."""
    result = parse_filters("artist:equals:Beatles")
    assert isinstance(result, PropertyFilter)
    assert result.key == "artist"
    assert result.operator == FilterOperator.EQUALS
    assert result.value == "Beatles"


def test_parse_filters_list_single_item():
    """Test parsing a list with a single filter string."""
    result = parse_filters(["year:gte:2000"])
    assert isinstance(result, PropertyFilter)
    assert result.key == "year"
    assert result.operator == FilterOperator.GREATER_EQUAL
    assert result.value == "2000"


def test_parse_filters_list_multiple_items():
    """Test parsing a list of filters, which should be AND-ed together."""
    result = parse_filters(["status:equals:APPROVED", "year:gt:1990"])
    assert isinstance(result, FilterGroup)
    assert result.operator == "AND"
    assert len(result.filters) == 2
    assert result.filters[0].key == "status"
    assert result.filters[1].key == "year"


def test_parse_filters_dict_with_operator():
    """Test parsing a dictionary representing a complex filter group."""
    filter_dict = {
        "operator": "OR",
        "filters": ["status:equals:READY_TO_PLAY", "status:equals:APPROVED"],
    }
    result = parse_filters(filter_dict)
    assert isinstance(result, FilterGroup)
    assert result.operator == "OR"
    assert len(result.filters) == 2
    assert result.filters[0].value == "READY_TO_PLAY"
    assert result.filters[1].value == "APPROVED"


def test_parse_filters_dict_single_filter():
    """Test parsing a dictionary with a single filter string."""
    filter_dict = {"operator": "AND", "filters": ["artist:equals:Prince"]}
    result = parse_filters(filter_dict)
    assert isinstance(result, PropertyFilter)
    assert result.key == "artist"
    assert result.value == "Prince"


def test_parse_filters_empty_list():
    """Test that an empty list of filters returns None."""
    assert parse_filters([]) is None


def test_parse_filters_empty_dict():
    """Test that an empty dictionary returns None."""
    assert parse_filters({}) is None


def test_parse_filters_dict_with_empty_filters_list():
    """Test that a dict with an empty filters list returns None."""
    assert parse_filters({"operator": "AND", "filters": []}) is None
