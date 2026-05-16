from services.launch_service import build_deep_link, build_launch_links, build_start_parameter


def test_build_start_parameter_normalizes_channel_fields():
    assert (
        build_start_parameter(
            source="TikTok Ads",
            campaign="Pilot Day 1",
            medium="Short Video",
            content="Hook-01",
        )
        == "src_tiktok_ads__cmp_pilot_day_1__med_short_video__cnt_hook_01"
    )


def test_build_deep_link_uses_telegram_start_parameter():
    assert (
        build_deep_link("@my_bot", "src_tiktok__cmp_pilot")
        == "https://t.me/my_bot?start=src_tiktok__cmp_pilot"
    )


def test_build_launch_links_formats_caption_url():
    links = build_launch_links(
        {
            "bot_username": "my_bot",
            "default_caption": "Start here: {url}",
            "campaigns": [
                {
                    "enabled": True,
                    "name": "TikTok Hook",
                    "source": "tiktok",
                    "campaign": "pilot_day_1",
                    "medium": "short_video",
                    "content": "hook_memory",
                },
                {
                    "enabled": False,
                    "name": "Disabled",
                    "source": "telegram",
                    "campaign": "off",
                },
            ],
        }
    )

    assert len(links) == 1
    assert links[0]["source"] == "tiktok"
    assert links[0]["start_parameter"] == "src_tiktok__cmp_pilot_day_1__med_short_video__cnt_hook_memory"
    assert links[0]["url"] in links[0]["caption"]
