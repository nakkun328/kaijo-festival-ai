import tempfile
import unittest
from pathlib import Path

from daily_store import DailyStore
from memory_proposals import memory_candidate


class MemoryProposalTests(unittest.TestCase):
    def test_only_stable_non_sensitive_facts_are_candidates(self):
        self.assertEqual(memory_candidate('私はギターが好き。'), '私はギターが好き')
        self.assertEqual(memory_candidate('ピアノの練習を続けている。'), 'ピアノの練習を続けている')
        for text in ('今日は疲れた', '私はギターが好き？', '私は薬を続けている',
                     '私はパスワードを勉強している'):
            self.assertIsNone(memory_candidate(text))

    def test_proposal_requires_approval_and_can_be_dismissed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DailyStore(Path(directory) / 'daily.db')
            owner = store.create_identity()
            other = store.create_identity()
            proposal = store.propose_memory(owner, '私はギターが好き')
            self.assertEqual(store.memories(owner), [])
            self.assertIsNone(store.pending_memory_proposal(other))
            with self.assertRaises(ValueError):
                store.resolve_memory_proposal(other, proposal['id'], 'save')
            self.assertEqual(DailyStore(store.path).pending_memory_proposal(owner), proposal)
            self.assertIsNone(store.propose_memory(owner, '私はピアノが好き'))
            self.assertEqual(store.pending_memory_proposal(owner), proposal)
            store.resolve_memory_proposal(owner, proposal['id'], 'dismiss')
            self.assertIsNone(store.pending_memory_proposal(owner))
            self.assertIsNone(store.propose_memory(owner, '私はギターが好き'))
            next_proposal = store.propose_memory(owner, '私はピアノが好き')
            self.assertTrue(store.resolve_memory_proposal(owner, next_proposal['id'], 'save', 'ピアノを練習中'))
            self.assertEqual(store.memories(owner)[0]['content'], 'ピアノを練習中')
            with self.assertRaises(ValueError):
                store.resolve_memory_proposal(owner, next_proposal['id'], 'save')
