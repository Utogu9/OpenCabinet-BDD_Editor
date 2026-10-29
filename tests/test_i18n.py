import ast
import json
from pathlib import Path
from string import Formatter
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from editor_settings import read_settings, update_settings
from editor_location import choose_library
from editor_store import component
import i18n
from translations import SPANISH


class Variable:
    __hash__ = None
    def __eq__(self, other):
        return self is other
    def set(self, value):
        self.value = value


class Widget:
    def winfo_exists(self):
        return True
    def configure(self, **options):
        self.options = options


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()/'editor-setting.json'
        self.previous = i18n.language()
        self.addCleanup(lambda: i18n.set_language(self.previous,persist=False))
        i18n.initialize_language(self.path)

    def test_english_default_spanish_persistence_and_restart(self):
        self.assertEqual(i18n.language(),'en')
        self.assertEqual(i18n.tr('Front cover'),'Front cover')
        update_settings({'library':'my-library','custom':'keep'},self.path)
        i18n.set_language('es',self.path)
        self.assertEqual(i18n.tr('Front cover'),'Carátula frontal')
        i18n.set_language('en',persist=False)
        i18n.initialize_language(self.path)
        self.assertEqual(i18n.language(),'es')
        self.assertEqual(read_settings(self.path),{'library':'my-library','custom':'keep','language':'es'})
        with self.assertRaises(ValueError):
            i18n.set_language('invalid',self.path)
        self.assertEqual(i18n.language(),'es')

    def test_library_selection_preserves_language_and_unknown_preferences(self):
        update_settings({'language':'es','custom':123},self.path)
        directory = self.path.parent/'Library'
        output = directory/'Console'
        output.mkdir(parents=True)
        (output/'catalog.json').write_text(json.dumps({'schema_version':2,'system':'Console','games':{}}))
        choose_library(self.path.parent,self.path,Mock(return_value=str(directory)),Mock())
        self.assertEqual(read_settings(self.path),{'language':'es','custom':123,'library':str(directory)})

    def test_legacy_plural_settings_are_preserved_when_writing_singular_file(self):
        old = self.path.with_name('editor-settings.json')
        old.write_text(json.dumps({'language':'es','library':'saved-library','unknown':True}))
        i18n.initialize_language(self.path)
        self.assertEqual(i18n.language(),'es')
        i18n.set_language('en',self.path)
        self.assertTrue(old.exists())
        self.assertEqual(read_settings(self.path),{'language':'en','library':'saved-library','unknown':True})

    def test_live_variable_and_widget_translations_keep_format_values(self):
        variable = Variable()
        widget = i18n.localize(Widget(),'Import image')
        i18n.set_text(variable,'{v0:,} games / folders',v0=12)
        i18n.set_language('es',persist=False)
        i18n.refresh_translations()
        self.assertEqual(variable.value,'12 juegos / carpetas')
        self.assertEqual(widget.options['text'],'Importar imagen')
        i18n.set_language('en',persist=False)
        i18n.refresh_translations()
        self.assertEqual(variable.value,'12 games / folders')
        self.assertEqual(widget.options['text'],'Import image')

    def test_backend_validation_uses_selected_language(self):
        for language, message in [('en','Invalid folder name'),('es','Nombre de carpeta no permitido')]:
            i18n.set_language(language,persist=False)
            with self.assertRaisesRegex(ValueError,message):
                component('../unsafe')

    def test_translation_placeholders_match_and_runtime_literals_are_covered(self):
        def fields(message):
            return {field for _,field,_,_ in Formatter().parse(message) if field is not None}
        for english, spanish in SPANISH.items():
            self.assertEqual(fields(english),fields(spanish),english)
        folder = Path(__file__).resolve().parents[1]/'scripts'
        for name in ['artwork_editor','game_dialog','editor_store','editor_location','console_artwork','pdf_tools','dat_catalog','game_registration','catalog_rules','launch_editor','editor_entry','metadata_store','metadata_dialog','svg_tools','artwork_actions','image_comparison','images_to_pdf','manual_images_dialog','cbz_tools']:
            for node in ast.walk(ast.parse((folder/(name+'.py')).read_text(encoding='utf-8'))):
                if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name):
                    continue
                position = {'tr':0,'set_text':1,'localize':1,'localize_title':1,'localize_heading':2}.get(node.func.id)
                if position is not None and len(node.args)>position:
                    value = node.args[position]
                    if isinstance(value,ast.Constant) and isinstance(value.value,str):
                        self.assertIn(value.value,SPANISH,f'{name}:{node.lineno}')


if __name__=='__main__':
    unittest.main()
