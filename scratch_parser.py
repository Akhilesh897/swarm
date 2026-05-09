import sys
from src.core.date_parser import parse_dates
import datetime

# Mock today's date for consistent testing
class MockDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 5, 8)
datetime.date = MockDate

queries = [
    "apply leave from jan 12,2026 to jan 13,2026",
    "apply leave from jan 12 to jan 13",
    "tomorrow",
    "next week"
]

for q in queries:
    print(f"Query: {q}")
    print(f"Result: {parse_dates(q)}")
    print("-" * 20)
