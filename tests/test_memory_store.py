import tempfile
import unittest
from pathlib import Path

from memory_store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.tempdir.name) / "test.db")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_messages_are_returned_in_conversation_order(self):
        self.store.add_message("s1", "user", "最初")
        self.store.add_message("s1", "assistant", "次")
        self.assertEqual(
            self.store.recent_messages("s1"),
            [{"role": "user", "content": "最初"}, {"role": "assistant", "content": "次"}],
        )

    def test_recall_finds_relevant_japanese_memory(self):
        wanted = self.store.add_memory("ユーザーは週末に電子工作をしている")
        self.store.add_memory("ユーザーは辛い料理が好き")
        recalled = self.store.recall("電子工作の続きをやろう")
        self.assertEqual(recalled[0].id, wanted)

    def test_delete_memory(self):
        memory_id = self.store.add_memory("消す内容")
        self.assertTrue(self.store.delete_memory(memory_id))
        self.assertFalse(self.store.delete_memory(memory_id))

    def test_summary_marking(self):
        self.store.add_message("s1", "user", "覚えて")
        rows = self.store.unsummarized_messages("s1", 8)
        self.store.mark_summarized([rows[0]["id"]])
        self.assertEqual(self.store.unsummarized_messages("s1", 8), [])


if __name__ == "__main__":
    unittest.main()

