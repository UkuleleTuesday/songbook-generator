from __future__ import annotations

from enum import Enum
from typing import List, Union

from pydantic import BaseModel


class FilterOperator(Enum):
    EQUALS = "equals"
    CONTAINS = "contains"
    GREATER_THAN = "gt"
    GREATER_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_EQUAL = "lte"
    NOT_EQUALS = "ne"
    IN = "in"


class PropertyFilter(BaseModel):
    """Represents a single property filter condition."""

    key: str
    operator: FilterOperator
    value: Union[str, int, float, List[str]]

    def matches(self, file_properties: dict) -> bool:
        """Check if a file's properties match this filter."""
        prop_value = file_properties.get(self.key)
        if prop_value is None:
            return False

        if self.operator == FilterOperator.EQUALS:
            return str(prop_value) == str(self.value)
        elif self.operator == FilterOperator.CONTAINS:
            return str(self.value).lower() in str(prop_value).lower()
        elif self.operator == FilterOperator.GREATER_THAN:
            try:
                return float(prop_value) > float(self.value)
            except (ValueError, TypeError):
                return False
        elif self.operator == FilterOperator.GREATER_EQUAL:
            try:
                return float(prop_value) >= float(self.value)
            except (ValueError, TypeError):
                return False
        elif self.operator == FilterOperator.LESS_THAN:
            try:
                return float(prop_value) < float(self.value)
            except (ValueError, TypeError):
                return False
        elif self.operator == FilterOperator.LESS_EQUAL:
            try:
                return float(prop_value) <= float(self.value)
            except (ValueError, TypeError):
                return False
        elif self.operator == FilterOperator.NOT_EQUALS:
            return str(prop_value) != str(self.value)
        elif self.operator == FilterOperator.IN:
            return str(prop_value) in [str(v) for v in self.value]

        return False


class FilterGroup(BaseModel):
    """Represents a group of filters with AND/OR logic."""

    operator: str = "AND"  # "AND" or "OR"
    filters: List[Union[PropertyFilter, FilterGroup]]

    def matches(self, file_properties: dict) -> bool:
        """Check if a file's properties match this filter group."""
        if not self.filters:
            return True

        results = [f.matches(file_properties) for f in self.filters]

        if self.operator == "AND":
            return all(results)
        else:  # OR
            return any(results)


class FilterParser:
    """Parse filter strings into filter objects."""

    @staticmethod
    def parse_simple_filter(filter_str: str) -> PropertyFilter:
        """Parse a filter string like 'specialbooks:contains:regular' or 'year:gte:2000'"""
        parts = filter_str.split(":", 2)

        if len(parts) == 2:
            # Default to equals: "artist:Beatles"
            key, value = parts
            return PropertyFilter(key=key, operator=FilterOperator.EQUALS, value=value)
        elif len(parts) == 3:
            # Explicit operator: "specialbooks:contains:regular"
            key, op_str, value = parts
            try:
                operator = FilterOperator(op_str)
            except ValueError:
                raise ValueError(
                    f"Unknown operator: {op_str}. Valid operators: {[op.value for op in FilterOperator]}"
                )

            # Handle list values for 'in' operator
            if operator == FilterOperator.IN:
                value = [v.strip() for v in value.split(",")]

            return PropertyFilter(key=key, operator=operator, value=value)
        else:
            raise ValueError(
                f"Invalid filter format: {filter_str}. Use 'key:value' or 'key:operator:value'"
            )


def parse_filters(
    filters_param: Union[str, list, dict, None]
) -> Optional[Union[PropertyFilter, FilterGroup]]:
    """
    Parse the filters parameter from the API request into filter objects.

    Args:
        filters_param: Can be a string, list of strings, or dict representing filters

    Returns:
        PropertyFilter, FilterGroup, or None if no filters
    """
    if not filters_param:
        return None

    if isinstance(filters_param, str):
        # Single filter string
        return FilterParser.parse_simple_filter(filters_param)

    if isinstance(filters_param, list):
        # List of filter strings - combine with AND logic
        if not filters_param:
            return None
        parsed_filters = [
            FilterParser.parse_simple_filter(filter_str) for filter_str in filters_param
        ]

        if len(parsed_filters) == 1:
            return parsed_filters[0]
        else:
            return FilterGroup(filters=parsed_filters, operator="AND")

    if isinstance(filters_param, dict):
        # Complex filter object
        if "filters" in filters_param and filters_param["filters"]:
            filter_list = filters_param["filters"]
            operator = filters_param.get("operator", "AND")

            parsed_filters = []
            for f in filter_list:
                if isinstance(f, str):
                    parsed_filters.append(FilterParser.parse_simple_filter(f))
                # Future: could handle nested filter objects here

            if not parsed_filters:
                return None
            if len(parsed_filters) == 1:
                return parsed_filters[0]
            else:
                return FilterGroup(filters=parsed_filters, operator=operator)

    return None
