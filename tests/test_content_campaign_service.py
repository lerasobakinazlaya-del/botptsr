from services.content_campaign_service import build_campaign_items, validate_campaign_config


def test_build_campaign_items_creates_tracking_url_and_caption():
    items = build_campaign_items(
        {
            "campaign": "pilot",
            "bot_username": "my_bot",
            "items": [
                {
                    "id": "memory_01",
                    "platform": "tiktok",
                    "source": "tiktok",
                    "medium": "short_video",
                    "content": "memory_01",
                    "hook": "hook",
                    "caption": "Try: {url}",
                    "safe_copy_checked": True,
                }
            ],
        }
    )

    assert items[0]["start_parameter"] == "src_tiktok__cmp_pilot__med_short_video__cnt_memory_01"
    assert items[0]["url"] == "https://t.me/my_bot?start=src_tiktok__cmp_pilot__med_short_video__cnt_memory_01"
    assert items[0]["url"] in items[0]["caption"]


def test_validate_campaign_config_catches_missing_safety_and_duplicates():
    errors = validate_campaign_config(
        {
            "campaign": "pilot",
            "items": [
                {"id": "a", "platform": "tiktok", "source": "tiktok", "content": "same", "hook": "h", "caption": "c"},
                {"id": "b", "platform": "tiktok", "source": "tiktok", "content": "same", "hook": "h", "caption": "c"},
            ],
        }
    )

    assert any("safe_copy_checked" in error for error in errors)
    assert any("duplicate start_parameter" in error for error in errors)
