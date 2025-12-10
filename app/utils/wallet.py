import random


def generate_wallet_number() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(12))
