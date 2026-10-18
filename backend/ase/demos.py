"""Small, trusted benchmark fixtures. The demo provider is scripted, not an LLM."""

DEMOS = {
    "cart": {
        "name": "Checkout total",
        "task": "Fix calculate_total: include item quantities and reject discounts outside 0..1.",
        "source": '''def calculate_total(items, discount=0.0):
    """Return the discounted checkout total."""
    subtotal = sum(item["price"] for item in items)
    return round(subtotal * (1 - discount), 2)
''',
        "first": '''def calculate_total(items, discount=0.0):
    """Return the discounted checkout total."""
    subtotal = sum(item["price"] * item["quantity"] for item in items)
    return round(subtotal * (1 - discount), 2)
''',
        "fixed": '''def calculate_total(items, discount=0.0):
    """Return the discounted checkout total."""
    if not 0 <= discount <= 1:
        raise ValueError("discount must be between 0 and 1")
    subtotal = sum(item["price"] * item["quantity"] for item in items)
    return round(subtotal * (1 - discount), 2)
''',
        "tests": """import pytest
from src.solution import calculate_total


def test_quantities():
    assert calculate_total([{"price": 10, "quantity": 3}]) == 30


def test_discount():
    assert calculate_total([{"price": 20, "quantity": 2}], 0.25) == 30


def test_empty_cart():
    assert calculate_total([]) == 0


@pytest.mark.parametrize("discount", [-0.1, 1.1])
def test_invalid_discount(discount):
    with pytest.raises(ValueError):
        calculate_total([], discount)
""",
    },
    "slug": {
        "name": "URL slug normalization",
        "task": "Fix slugify to collapse whitespace, strip surrounding spaces, and lowercase text.",
        "source": '''def slugify(text):
    """Normalize a title into a simple URL slug."""
    return text.replace(" ", "-")
''',
        "first": '''def slugify(text):
    """Normalize a title into a simple URL slug."""
    return text.lower().strip().replace(" ", "-")
''',
        "fixed": '''def slugify(text):
    """Normalize a title into a simple URL slug."""
    return "-".join(text.lower().split())
''',
        "tests": """from src.solution import slugify


def test_lowercase():
    assert slugify("Hello World") == "hello-world"


def test_surrounding_space():
    assert slugify("  hello  ") == "hello"


def test_repeated_whitespace():
    assert slugify("Hello   World\\tAgain") == "hello-world-again"


def test_empty():
    assert slugify("   ") == ""
""",
    },
    "median": {
        "name": "Median edge cases",
        "task": (
            "Fix median: sort without mutating input, average even-length middles, reject empty."
        ),
        "source": '''def median(values):
    """Return the median of a sequence of numbers."""
    return values[len(values) // 2]
''',
        "first": '''def median(values):
    """Return the median of a sequence of numbers."""
    ordered = sorted(values)
    return ordered[len(ordered) // 2]
''',
        "fixed": '''def median(values):
    """Return the median of a sequence of numbers."""
    if not values:
        raise ValueError("median needs at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
''',
        "tests": """import pytest
from src.solution import median


def test_odd_unsorted():
    assert median([9, 1, 5]) == 5


def test_even():
    assert median([1, 9, 3, 7]) == 5


def test_input_unchanged():
    values = [9, 1, 5]
    median(values)
    assert values == [9, 1, 5]


def test_empty():
    with pytest.raises(ValueError):
        median([])
""",
    },
}


def write_demo(root, scenario):
    spec = DEMOS[scenario]
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src/__init__.py").write_text("", encoding="utf-8")
    (root / "src/solution.py").write_text(spec["source"], encoding="utf-8")
    (root / "tests/test_solution.py").write_text(spec["tests"], encoding="utf-8")
    (root / "README.md").write_text(spec["task"] + "\n", encoding="utf-8")
