import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from festival_knowledge import FestivalKnowledgeBase, is_festival_question, requested_organization


class FestivalKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "knowledge.json"
        self.path.write_text(json.dumps({
            "metadata": {"festival_name": "テスト祭", "source_file": "test.pdf"},
            "records": [
                {
                    "id": "physics", "event_name": "物理部実験ショー", "organization": "物理部",
                    "category": "展示・実験", "location": "2号館3階 物理室", "day": "土・日",
                    "start_time": "10:00", "end_time": "15:00", "description": "実験を実演する",
                    "keywords": ["科学", "実験"], "page": 34,
                },
                {
                    "id": "food", "event_name": "焼きそば", "organization": "高校2年",
                    "category": "食品", "location": "カフェテリア", "day": "土・日",
                    "start_time": "11:00", "end_time": "14:00", "description": "焼きそばを販売",
                    "keywords": ["ご飯", "飲食"], "page": 11,
                },
            ],
        }, ensure_ascii=False), encoding="utf-8")
        self.kb = FestivalKnowledgeBase(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_and_status(self):
        self.assertTrue(self.kb.ready)
        self.assertEqual(self.kb.status()["recordCount"], 2)

    def test_japanese_search_and_synonym_expansion(self):
        self.assertEqual(self.kb.search("科学の展示")[0].record["id"], "physics")
        self.assertEqual(self.kb.search("ご飯はどこ？")[0].record["id"], "food")

    def test_context_has_grounding_rules_and_page(self):
        context = self.kb.build_context(
            "物理部はどこ？", now=datetime(2026, 9, 19, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
        )
        self.assertIn("推測せず", context)
        self.assertIn("ページ=34", context)
        self.assertIn("2026-09-19 12:00", context)

    def test_missing_file_is_safe(self):
        kb = FestivalKnowledgeBase(Path(self.temp_dir.name) / "missing.json")
        self.assertFalse(kb.ready)
        self.assertIn("ありません", kb.status()["reason"])

    def test_guide_intent_detection(self):
        self.assertTrue(is_festival_question("文化祭で今から食べられるものは？"))
        self.assertFalse(is_festival_question("最近ハマってるゲームの話をしよう"))
        self.assertFalse(is_festival_question("現在の日時を教えて"))
        self.assertTrue(is_festival_question("文化祭は今何時まで？"))

    def test_now_query_outside_festival_is_explicit(self):
        context = self.kb.build_context(
            "今から参加できる企画は？",
            now=datetime(2026, 9, 10, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
        )
        self.assertIn("今日は開催日ではない", context)

    def test_exact_event_name_enables_grounding(self):
        self.assertTrue(self.kb.should_ground("物理部実験ショーってどんなもの？"))

    def test_select_for_answer_prefers_the_fact_cited_by_page_and_location(self):
        selected = self.kb.select_for_answer(
            "科学の展示はどこ？",
            "物理部実験ショーは2号館3階の物理室です（パンフレットp.34）。",
        )
        self.assertEqual([record["id"] for record in selected], ["physics"])

    def test_get_record_uses_stable_id(self):
        self.assertEqual(self.kb.get_record("food")["event_name"], "焼きそば")
        self.assertIsNone(self.kb.get_record("missing"))

    def test_general_recommendation_prioritizes_physics_club(self):
        results = self.kb.search("文化祭のおすすめは？")
        self.assertEqual(results[0].record["id"], "physics")
        context = self.kb.build_context("文化祭のおすすめは？")
        self.assertIn("物理部の一般展示", context)
        self.assertIn("第一候補", context)

    def test_specific_food_recommendation_keeps_the_user_constraint(self):
        results = self.kb.search("食べ物のおすすめは？")
        self.assertEqual(results[0].record["id"], "food")

    def test_uncertain_answer_does_not_show_an_unrelated_card(self):
        selected = self.kb.select_for_answer(
            "ドラゴン研究部の展示はどこ？",
            "パンフレットでは確認できないため、受付で確認してくれ。",
        )
        self.assertEqual(selected, [])
        self.assertEqual(
            self.kb.select_for_answer(
                "ドラゴン研究部の展示はどこ？",
                "パンフレットには載ってないみたいだ。",
            ),
            [],
        )
        self.assertEqual(
            self.kb.select_for_answer(
                "ドラゴン研究部の展示はどこ？",
                "その団体の情報は見つけられなかったよ。",
            ),
            [],
        )

    def test_missing_named_organization_is_not_replaced_by_a_similar_club(self):
        self.assertEqual(requested_organization("ドラゴン研究部の展示はどこ？"), "ドラゴン研究部")
        context = self.kb.build_context("ドラゴン研究部の展示はどこ？")
        self.assertIn("完全一致する記載がない", context)
        self.assertIn("似た名前の別団体", context)
        self.assertNotIn("名称=物理部実験ショー", context)

    def test_recommendation_card_selection_keeps_physics_first(self):
        selected = self.kb.select_for_answer(
            "理科系でおすすめの展示は？",
            "物理部の物理部実験ショー（p.34）と焼きそば（p.11）がおすすめ。",
        )
        self.assertEqual(selected[0]["id"], "physics")

    def test_where_when_answers_receive_exact_confirmation_fields(self):
        answer = self.kb.ensure_requested_details(
            "物理部実験ショーはいつどこ？",
            "物理部実験ショーは午前中に物理室でやるぞ。",
        )
        self.assertIn("時間: 10:00-15:00", answer)
        self.assertIn("場所: 2号館3階 物理室", answer)
        self.assertIn("パンフレットp.34", answer)

    def test_additional_official_website_source_is_searchable_and_attributed(self):
        website_path = Path(self.temp_dir.name) / "website.json"
        website_path.write_text(json.dumps({
            "metadata": {
                "festival_name": "テスト祭",
                "source_file": "https://example.test/booths",
            },
            "records": [{
                "id": "web-only", "event_name": "公式サイト限定企画", "organization": "広報部",
                "category": "展示", "location": "1号館1階", "date": "2026-09-19",
                "day": "土", "start_time": "", "end_time": "", "description": "サイト掲載情報",
                "keywords": ["限定"], "page": "", "source_type": "official_website",
                "source_label": "海城祭公式サイト", "source_url": "https://example.test/booths",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        kb = FestivalKnowledgeBase(self.path, additional_paths=[website_path])

        self.assertEqual(kb.search("公式サイト限定企画")[0].record["id"], "web-only")
        self.assertEqual(kb.status()["recordCount"], 3)
        context = kb.build_context("公式サイト限定企画はどこ？")
        self.assertIn("出典=海城祭公式サイト", context)
        self.assertNotIn("ページ=999", context)
        answer = kb.ensure_requested_details("公式サイト限定企画はどこ？", "1号館にあるぞ。")
        self.assertIn("海城祭公式サイト", answer)


if __name__ == "__main__":
    unittest.main()
