import unittest
from unittest.mock import MagicMock, patch
from daily_tools import DailyTools


class DailyToolsTests(unittest.TestCase):
    def test_invalid_plan_cannot_select_arbitrary_tool(self):
        provider = MagicMock()
        provider.generate.return_value = '{"tool":"shell","query":"whoami"}'
        plan = DailyTools().plan(provider, '天気を調べて', [])
        self.assertEqual(plan['tool'], 'none')
        self.assertIn('error', plan)

    def test_casual_chat_skips_tool_planning_model_call(self):
        provider = MagicMock()
        self.assertEqual(DailyTools().plan(provider, 'ありがとう', [])['tool'], 'none')
        provider.generate.assert_not_called()

    def test_weather_followup_still_checks_tool(self):
        provider = MagicMock()
        provider.generate.return_value = '{"tool":"weather","query":"東京"}'
        plan = DailyTools().plan(provider, '明日は？', [{'role':'user','content':'東京の天気は？'}])
        self.assertEqual(plan['tool'], 'weather')
        provider.generate.assert_called_once()

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

    def test_react_uses_observation_to_choose_second_tool(self):
        tools = DailyTools()
        provider = MagicMock()
        provider.generate.side_effect = [
            '{"tool":"search","query":"東京 明日 イベント"}',
            '{"tool":"weather","query":"東京"}',
            '{"tool":"none","query":""}',
        ]
        with patch.object(tools, 'search', return_value={
            'sources':[{'title':'催し','url':'https://example.com/event','snippet':'屋外イベント'}]}) as search, \
                patch.object(tools, 'weather', return_value={
                    'forecast':{'daily':{'temperature_2m_max':[25]}},
                    'sources':[{'title':'天気','url':'https://example.com/weather'}]}) as weather:
            events = list(tools.react(provider, '東京の明日のイベントと天気を調べて', []))
        self.assertEqual([event['tool'] for event in events if event['type'] == 'action'], ['search','weather'])
        self.assertEqual(len(events[-1]['result']['steps']), 2)
        self.assertEqual(len(events[-1]['result']['sources']), 2)
        self.assertIn('屋外イベント', provider.generate.call_args_list[1].args[1][0]['content'])
        search.assert_called_once_with('東京 明日 イベント')
        weather.assert_called_once_with('東京')

    def test_react_stops_repeated_action(self):
        tools = DailyTools()
        provider = MagicMock()
        provider.generate.return_value = '{"tool":"search","query":"最新ニュース"}'
        with patch.object(tools, 'search', return_value={'sources':[]}) as search:
            events = list(tools.react(provider, '最新ニュースを調べて', []))
        search.assert_called_once()
        self.assertEqual(len(events[-1]['result']['steps']), 1)
        self.assertIn('error', events[-1]['result'])

    def test_react_casual_chat_uses_no_tool_or_model_call(self):
        provider = MagicMock()
        events = list(DailyTools().react(provider, 'ありがとう', []))
        self.assertEqual(events[-1]['result']['steps'], [])
        provider.generate.assert_not_called()
