import unittest
from memory_commands import PROPOSAL_QUESTION, parse_memory_command, proposal_reply, resolve_memory_action


class MemoryCommandTests(unittest.TestCase):
    def test_explicit_save_and_context_reference(self):
        self.assertEqual(parse_memory_command('私はギターが好き。覚えておいて'), ('save','私はギターが好き'))
        action = resolve_memory_action(('save','これ'), [{'role':'user','content':'ギターを練習中'}], [])
        self.assertEqual(action, {'action':'save', 'content':'ギターを練習中'})
        request_history = [{'role':'user','content':'進路の選択肢を整理して'},
                           {'role':'assistant','content':'大学と就職があるね。'}]
        self.assertIn('question', resolve_memory_action(('save','これ'), request_history, []))

    def test_ambiguous_forget_does_not_delete(self):
        self.assertEqual(parse_memory_command('それはもう忘れて'), ('forget', 'それ'))
        memories = [{'id':1,'content':'ギターが好き'}, {'id':2,'content':'ギターの練習中'}]
        self.assertIn('question', resolve_memory_action(('forget','それ'), [], memories))
        self.assertIn('question', resolve_memory_action(('forget','ギター'), [], memories))

    def test_that_forget_only_targets_immediately_confirmed_memory(self):
        memories = [{'id':1,'content':'ギターが好き'}, {'id':2,'content':'ピアノが好き'}]
        history = [{'role':'user','content':'ギターが好き。覚えておいて'},
                   {'role':'assistant','content':'覚えたよ。「ギターが好き」'}]
        self.assertEqual(resolve_memory_action(('forget','それ'), history, memories)['id'], 1)
        history.append({'role':'user','content':'今日は何を話そうか'})
        history.append({'role':'assistant','content':'音楽の話でもしようか。'})
        self.assertIn('question', resolve_memory_action(('forget','それ'), history, memories))
        duplicate = memories + [{'id':3,'content':'ギターが好き'}]
        self.assertIn('question', resolve_memory_action(('forget','それ'), history[:2], duplicate))

    def test_unique_forget_selects_one(self):
        memories = [{'id':4,'content':'毎週火曜はギターを練習'}, {'id':5,'content':'ピアノが好き'}]
        self.assertEqual(resolve_memory_action(('forget','ギターのこと'), [], memories)['id'],4)

    def test_ordinary_chat_not_a_command(self):
        self.assertIsNone(parse_memory_command('覚えている？'))
        self.assertIsNone(parse_memory_command('ギターを忘れたかもしれない'))

    def test_short_reply_only_resolves_immediately_asked_proposal(self):
        pending = {'id':1, 'content':'私はギターが好き'}
        asked = [{'role':'assistant', 'content':'いいね。\n' + PROPOSAL_QUESTION}]
        self.assertEqual(proposal_reply('うん。', asked, pending), 'save')
        self.assertEqual(proposal_reply('今はいい', asked, pending), 'dismiss')
        self.assertIsNone(proposal_reply('うん', [{'role':'assistant','content':'いいね。'}], pending))
        self.assertIsNone(proposal_reply('うん', asked, None))
        self.assertIsNone(proposal_reply('たぶん', asked, pending))
