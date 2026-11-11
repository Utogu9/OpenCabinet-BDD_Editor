from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from artwork_editor import Editor


class ReloadSelectionTests(unittest.TestCase):
    def test_reload_refreshes_cards_without_waiting_for_tree_selection_event(self):
        editor = Editor.__new__(Editor)
        output = Path('Console')
        editor.current_output = output
        editor.store = Mock()
        editor.store.read_catalog.return_value = {'games': {'ID': {'images': {'cover_front': {'sha256': 'new'}}}}}
        events = []
        editor.filter_games = Mock(side_effect=lambda: events.append('filter'))
        editor.select_game = Mock(side_effect=lambda: events.append('refresh'))
        editor.reload_game(output, 'ID')
        self.assertEqual(events, ['filter', 'refresh'])
        self.assertEqual(editor.games['ID']['images']['cover_front']['sha256'], 'new')


if __name__ == '__main__':
    unittest.main()
