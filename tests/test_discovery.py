def test_env_override_discovery(monkeypatch):
    import sync

    # Ensure the override refers to an existing function name
    monkeypatch.setenv("EBT_GET_LOCAL_FN", "get_local_items")
    # _discover reads env var each call and validates against ebay_inventory
    assert sync._discover("local") == "get_local_items"

