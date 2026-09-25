import unittest
from unittest.mock import patch
from daily_tools import DailyTools


class DailyToolsTests(unittest.TestCase):
    def test_invalid_tool_cannot_run(self):
        with self.assertRaises(ValueError):
            DailyTools().run({'tool':'shell','query':'whoami'})

    def test_casual_chat_skips_live_agent(self):
        self.assertFalse(DailyTools().needs_live_info('ありがとう', []))

    def test_weather_followup_still_uses_live_agent(self):
        self.assertTrue(DailyTools().needs_live_info(
            '明日は？', [{'role':'user','content':'東京の天気は？'}]))

    def test_weather_without_location_never_fetches(self):
        tools = DailyTools()
        with patch.object(tools, 'weather') as weather:
            result = tools.run({'tool':'weather', 'query':''})
        weather.assert_not_called()
        self.assertIn('clarification', result)
        self.assertEqual(result['sources'], [])

    def test_outage_does_not_invent_weather_or_sources(self):
        tools = DailyTools()
        with patch.object(tools, 'weather', side_effect=TimeoutError):
            result = tools.run({'tool':'weather', 'query':'東京'})
        self.assertIn('error', result)
        self.assertEqual(result['sources'], [])
        self.assertNotIn('forecast', result)

    def test_search_filters_unsafe_links_and_limits_excerpt(self):
        with patch('ddgs.DDGS') as search:
            search.return_value.text.return_value = [
                {'href':'javascript:alert(1)', 'title':'unsafe'},
                {'href':'https://example.com', 'title':'source', 'body':'x'*5000}]
            result = DailyTools().search('test')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(len(result['sources'][0]['snippet']), 1200)
