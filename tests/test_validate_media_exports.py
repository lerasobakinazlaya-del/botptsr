import unittest

from scripts.validate_media_exports import has_mojibake, video_stream, audio_stream


class ValidateMediaExportsTests(unittest.TestCase):
    def test_detects_mojibake(self):
        self.assertTrue(has_mojibake("РќРёС‚СЊ РѕРЅР»Р°Р№РЅ В«С‚РµСЃС‚В»"))
        self.assertFalse(has_mojibake("Нить онлайн. Попробуй один спокойный диалог."))

    def test_extracts_streams(self):
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        }
        self.assertEqual(video_stream(probe)["codec_name"], "h264")
        self.assertEqual(audio_stream(probe)["codec_name"], "aac")

    def test_missing_streams_return_none(self):
        self.assertIsNone(video_stream({"streams": []}))
        self.assertIsNone(audio_stream({"streams": [{"codec_type": "video"}]}))


if __name__ == "__main__":
    unittest.main()
