from app.statuses import CANONICAL, STATUS_MAP, canonical_status


def test_known_mappings():
    assert canonical_status("stripe", "succeeded") == "collected"
    assert canonical_status("stripe", "refunded") == "refunded"
    assert canonical_status("hubspot", "closedwon") == "collected"
    assert canonical_status("hubspot", "closedlost") == "failed"


def test_lookup_is_case_insensitive():
    assert canonical_status("stripe", "Succeeded") == "collected"


def test_unknown_status_never_counts_as_collected():
    # a status Stripe ships tomorrow, and a source we've never heard of:
    # both must land as "unknown", not slip through as revenue
    assert canonical_status("stripe", "requires_confirmation_v2") == "unknown"
    assert canonical_status("brand_new_source", "paid") == "unknown"
    assert canonical_status("stripe", "") == "unknown"


def test_every_mapping_targets_a_canonical_status():
    for source, mapping in STATUS_MAP.items():
        for raw, canon in mapping.items():
            assert canon in CANONICAL, f"{source}.{raw} -> {canon} is not canonical"
