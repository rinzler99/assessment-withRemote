"""Seed the HubSpot portal with a few contacts and deals.

Needs a private app token with contacts + deals write scopes. Contacts are
deduped by email (HubSpot 409s on duplicates, which we treat as 'already
seeded'); re-running the deals part will create extra deals, so run once.
"""

import time

import httpx

from app import config

CONTACTS = [
    {"firstname": "Ava", "lastname": "Sharma", "email": "ava.sharma@example.com"},
    {"firstname": "Marcus", "lastname": "Webb", "email": "marcus.webb@example.com"},
    {"firstname": "Priya", "lastname": "Iyer", "email": "priya.iyer@example.com"},
    {"firstname": "Tom", "lastname": "Okafor", "email": "tom.okafor@example.com"},
    {"firstname": "Lena", "lastname": "Fischer", "email": "lena.fischer@example.com"},
]

# dealstage values are the default sales pipeline's internal stage ids
DEALS = [
    {"dealname": "Acme Co - annual contract", "amount": "4990", "dealstage": "closedwon"},
    {"dealname": "Initech - renewal", "amount": "2400", "dealstage": "closedwon"},
    {"dealname": "Globex - pilot", "amount": "1200", "dealstage": "presentationscheduled"},
    {"dealname": "Hooli - expansion", "amount": "8000", "dealstage": "contractsent"},
    {"dealname": "Umbrella - churned", "amount": "1500", "dealstage": "closedlost"},
]


def main():
    assert config.HUBSPOT_TOKEN, "set HUBSPOT_TOKEN first"
    client = httpx.Client(
        base_url="https://api.hubapi.com",
        headers={"Authorization": f"Bearer {config.HUBSPOT_TOKEN}"},
        timeout=30,
    )

    for props in CONTACTS:
        resp = client.post("/crm/v3/objects/contacts", json={"properties": props})
        if resp.status_code == 409:
            print(f"contact {props['email']} already exists, skipping")
        else:
            resp.raise_for_status()
            print(f"created contact {props['email']} -> {resp.json()['id']}")

    three_days_ago_ms = int((time.time() - 3 * 86400) * 1000)
    for props in DEALS:
        if props["dealstage"] in ("closedwon", "closedlost"):
            props = {**props, "closedate": str(three_days_ago_ms)}
        resp = client.post("/crm/v3/objects/deals", json={"properties": props})
        resp.raise_for_status()
        print(f"created deal {props['dealname']!r} -> {resp.json()['id']}")


if __name__ == "__main__":
    main()
