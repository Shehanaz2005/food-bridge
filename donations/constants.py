"""Shared constants for food data used across profiles and donations."""

FOOD_CATEGORY_CHOICES = [
    ("cooked_meal", "Cooked Meals"),
    ("bakery", "Bakery & Breads"),
    ("fruits_vegetables", "Fruits & Vegetables"),
    ("dairy", "Dairy & Eggs"),
    ("packaged", "Packaged & Dry Food"),
    ("beverages", "Beverages"),
    ("other", "Other"),
]

FOOD_UNIT_CHOICES = [
    ("kg", "Kilograms (kg)"),
    ("meals", "Meals / Servings"),
    ("packets", "Packets"),
    ("litres", "Litres"),
    ("pieces", "Pieces"),
]

# Compact labels for inline display, e.g. "20 meals" instead of
# "20 Meals / Servings".
FOOD_UNIT_SHORT_LABELS = {
    "kg": "kg",
    "meals": "meals",
    "packets": "packets",
    "litres": "litres",
    "pieces": "pieces",
}

CATEGORY_ICONS = {
    "cooked_meal": "fa-bowl-food",
    "bakery": "fa-bread-slice",
    "fruits_vegetables": "fa-carrot",
    "dairy": "fa-egg",
    "packaged": "fa-box-open",
    "beverages": "fa-mug-hot",
    "other": "fa-utensils",
}
