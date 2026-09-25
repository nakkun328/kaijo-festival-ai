import unittest
from unittest.mock import MagicMock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from langchain_daily_agent import LangChainDailyAgent


class ToolCallingFake(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class LangChainDailyAgentTests(unittest.TestCase):
    def test_agent_observes_tool_result_before_answering(self):
        model = ToolCallingFake(responses=[
            AIMessage(content='', tool_calls=[{
                'name':'search', 'args':{'query':'東京のニュース'}, 'id':'call-1',
            }]),
            AIMessage(content='確認できたニュースです。[1]'),
        ])
        tools = MagicMock()
        tools.run.return_value = {
            'tool':'search', 'retrievedAt':'2026-09-24T00:00:00+00:00',
            'sources':[{'title':'記事','url':'https://example.com/news','snippet':'確認済み'}],
        }
        with patch('langchain_daily_agent.build_chat_model', return_value=model):
            events = list(LangChainDailyAgent(tools).stream(
                MagicMock(), '日本語で答えて',
                [{'role':'user','content':'東京のニュースを調べて'}], 300,
            ))
        self.assertEqual(events[-1]['answer'], '確認できたニュースです。[1]')
        self.assertEqual(events[-1]['tool_result']['sources'][0]['url'], 'https://example.com/news')
        self.assertEqual(events[-1]['tool_result']['steps'][0]['tool'], 'search')
        tools.run.assert_called_once_with({'tool':'search', 'query':'東京のニュース'})

    def test_repeated_tool_request_does_not_fetch_twice(self):
        model = ToolCallingFake(responses=[
            AIMessage(content='', tool_calls=[{'name':'search','args':{'query':'同じ検索'},'id':'call-1'}]),
            AIMessage(content='', tool_calls=[{'name':'search','args':{'query':'同じ検索'},'id':'call-2'}]),
            AIMessage(content='これ以上確認できません。'),
        ])
        tools = MagicMock()
        tools.run.return_value = {'tool':'search', 'retrievedAt':'now', 'sources':[]}
        with patch('langchain_daily_agent.build_chat_model', return_value=model):
            events = list(LangChainDailyAgent(tools).stream(
                MagicMock(), '答えて', [{'role':'user','content':'同じ検索をして'}], 300,
            ))
        self.assertEqual(events[-1]['answer'], 'これ以上確認できません。')
        self.assertEqual(len(events[-1]['tool_result']['steps']), 1)
        tools.run.assert_called_once()
