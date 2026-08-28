from decimal import Decimal


def average(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))
