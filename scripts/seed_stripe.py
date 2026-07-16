"""Create a handful of test-mode payments in Stripe: several successful,
one refunded, one declined. Re-running just adds more, so run once.
"""

import httpx

from app import config

PAYMENTS = [
    (12900, "Starter plan - Acme Co"),
    (49900, "Annual plan - Globex"),
    (7500, "Add-on seats - Initech"),
    (25000, "Consulting retainer - Hooli"),
]


def main():
    assert config.STRIPE_SECRET_KEY, "set STRIPE_SECRET_KEY first"
    assert config.STRIPE_SECRET_KEY.startswith("sk_test_"), "refusing to seed with a live key"
    client = httpx.Client(
        base_url="https://api.stripe.com/v1",
        auth=(config.STRIPE_SECRET_KEY, ""),
        timeout=30,
    )

    for amount, description in PAYMENTS:
        pi = _pay(client, amount, description, "pm_card_visa")
        print(f"created {pi['id']} ({description}) -> {pi['status']}")

    pi = _pay(client, 9900, "Monthly plan - Wayne Corp (refunded)", "pm_card_visa")
    resp = client.post("/refunds", data={"charge": pi["latest_charge"]})
    resp.raise_for_status()
    print(f"refunded {pi['latest_charge']}")

    # a declined card, so there's a failed charge in the data too
    resp = client.post("/payment_intents", data=_pi_body(4200, "Trial - Stark Industries", "pm_card_chargeDeclined"))
    print(f"declined attempt -> HTTP {resp.status_code} (expected; card is a test decline)")


def _pay(client, amount, description, payment_method):
    resp = client.post("/payment_intents", data=_pi_body(amount, description, payment_method))
    resp.raise_for_status()
    return resp.json()


def _pi_body(amount, description, payment_method):
    return {
        "amount": amount,
        "currency": "usd",
        "description": description,
        "payment_method": payment_method,
        "confirm": "true",
        "automatic_payment_methods[enabled]": "true",
        "automatic_payment_methods[allow_redirects]": "never",
    }


if __name__ == "__main__":
    main()
