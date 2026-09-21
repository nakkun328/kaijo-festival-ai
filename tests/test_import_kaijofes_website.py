import json
import unittest

from scripts.import_kaijofes_website import build_payload


class KaijoWebsiteImportTests(unittest.TestCase):
    def test_embedded_next_data_is_converted_with_per_day_times(self):
        top_html = """
        <main>第135代 海城祭 2026. 9.19-9.20. 9:00 - 16:00
        〒169-0072 東京都新宿区大久保3-6-1 Google Map</main>
        """
        booths = [{
            "id": "H99",
            "section": "講堂企画",
            "locations": [{"name": "講堂", "building": "1号館", "floor": 2}],
            "heldOnSaturday": True,
            "heldOnSunday": True,
            "saturdayStart": "10:00",
            "saturdayEnd": "11:00",
            "sundayStart": "14:00",
            "sundayEnd": "15:00",
            "organization": "テスト部",
            "title": "テスト公演",
            "description": "公式サイトの説明",
        }]
        flight_payload = '11:["$","component",null,{"booths":' + json.dumps(
            booths, ensure_ascii=False, separators=(",", ":")
        ) + '}]'
        script_argument = json.dumps([1, flight_payload], ensure_ascii=False)
        booths_html = f"<script>self.__next_f.push({script_argument})</script>"

        payload = build_payload(top_html, booths_html)

        self.assertEqual(payload["metadata"]["festival_dates"], ["2026-09-19", "2026-09-20"])
        event_records = payload["records"][1:]
        self.assertEqual([item["id"] for item in event_records], ["web-H99-sat", "web-H99-sun"])
        self.assertEqual(event_records[0]["location"], "1号館2階 講堂")
        self.assertEqual(event_records[1]["start_time"], "14:00")
        self.assertEqual(event_records[0]["source_label"], "海城祭公式サイト")


if __name__ == "__main__":
    unittest.main()
