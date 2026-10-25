from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from dat_catalog import DatCache, providers
from catalog_rules import canonical_serial


def dat(name, games):
    return ('<datafile><header><name>'+name+'</name><version>fixture</version></header>'+games+'</datafile>').encode()


class DatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = DatCache(Path(self.temp.name)/'cache')

    def test_serial_normalization_exclusions_collisions_and_wii_title_ids(self):
        self.assertEqual(canonical_serial('slus 12345-GER'),'SLUS-12345-GER')
        raw = dat('Sony - PlayStation',
            '<game id="100" name="Example (USA)"><serial>SLUS12345, !NONE</serial></game>'
            '<game id="101" name="Slash (USA)"><serial>A/B</serial></game>'
            '<game id="102" name="Literal (USA)"><serial>A-B</serial></game>'
            '<game id="103" name="Missing (USA)"><archive number="9999"/></game>')
        catalog = self.cache.import_bytes('Sony - PlayStation','redump',raw)
        self.assertEqual(catalog.routes['SLUS-12345']['folder'],'SLUS-12345')
        self.assertEqual(catalog.routes['!NONE']['status'],'excluded')
        self.assertEqual(catalog.routes['A/B']['status'],'collision')
        self.assertEqual(catalog.by_id['103']['serials'],[])
        digital = dat('Nintendo - Wii (Digital) (CDN)',
            '<game id="1" name="Channel (USA)"><game_id>0001000157414945</game_id></game>')
        wii = self.cache.import_bytes('Nintendo - Wii','no-intro',digital)
        self.assertEqual(wii.entries[0]['redump_id'],'no-intro:1')
        self.assertEqual(wii.entries[0]['serials'],['0001000157414945'])
        gp = self.cache.import_bytes('GamePark - GP32','no-intro',dat('GamePark - GP32',
            '<game id="1" name="Example"><serial>1</serial><game_id>0001000157414945</game_id></game>'))
        self.assertEqual(gp.routes['1']['status'],'excluded')
        self.assertEqual(providers('Nintendo - Wii'),['redump','no-intro'])

    def test_search_preserves_regions_revisions_disc_labels_and_uses_articles(self):
        catalog = self.cache.import_bytes('Sony - PlayStation','redump',dat('Sony - PlayStation',
            '<game id="1" name="Example, The (Japan, Asia) (En,Ja)"><serial>TEST-1</serial></game>'
            '<game id="2" name="The Example (USA) (Rev 1)"><serial>TEST-2</serial></game>'
            '<game id="3" name="The Example (USA) (Disc 2)"><serial>TEST-3</serial></game>'
            '<game id="4" name="The Example (USA) (v1.02)"><serial>TEST-4</serial></game>'))
        found, _ = catalog.search('the example (Japan)')
        self.assertEqual([e['redump_id'] for e in found],['1'])
        self.assertEqual(catalog.search('The Example (USA) (Rev 1)')[0][0]['redump_id'],'2')
        self.assertEqual(catalog.search('The Example (USA) (Disc 2)')[0][0]['redump_id'],'3')
        self.assertEqual(catalog.search('The Example (USA) (v1.02)')[0][0]['redump_id'],'4')
        self.assertEqual(catalog.search('TEST-1')[0][0]['redump_id'],'1')
        self.assertEqual(catalog.search('example')[1],4)

    def test_no_intro_db_fills_only_missing_primary_serials_and_updates_from_original(self):
        standard = dat('Nintendo - Game Boy Advance',
            '<game id="1" name="Existing (USA)"><serial>AGB-ORIG-USA</serial></game>'
            '<game id="2" name="New (USA)"/><game id="3" name="New (Japan)"/>')
        self.cache.import_bytes('Nintendo - Game Boy Advance','no-intro',standard)
        def database(code):
            return ('<header><version>fixture</version></header><datafile>'
                '<game name="Existing (USA)"><source><details id="10"/><serials media_serial1="OVERRIDE"/><file/></source></game>'
                '<game name="New (USA)"><source><details id="11"/><serials media_serial1="'+code+'" pcb_serial="NOT-A-SERIAL"/><file/></source>'
                '<source><details id="12" rominfo="bad"/><serials media_serial1="BAD"/><file/></source></game></datafile>').encode()
        name = 'Nintendo - Game Boy Advance (DB Export) (fixture).xml'
        catalog = self.cache.import_bytes('Nintendo - Game Boy Advance','no-intro',database('AGB-NEW-USA'),name)
        self.assertEqual(catalog.by_id['1']['serials'],['AGB-ORIG-USA'])
        self.assertEqual(catalog.by_id['2']['serials'],['AGB-NEW-USA'])
        self.assertEqual(catalog.by_id['3']['serials'],[])
        updated = self.cache.import_bytes('Nintendo - Game Boy Advance','no-intro',database('AGB-FIX-USA'),name)
        self.assertEqual(updated.by_id['2']['serials'],['AGB-FIX-USA'])

    def test_download_validates_payload_and_cache_survives_errors(self):
        raw = dat('Sony - PlayStation','<game id="1" name="Example"><serial>TEST-1</serial></game>')
        buffer = BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            z.writestr('psx.dat',raw)
        with patch.object(self.cache,'fetch',return_value=buffer.getvalue()):
            catalog = self.cache.download('Sony - PlayStation','redump')
        self.assertEqual(catalog.provenance['acquisition'],'official_download')
        with patch.object(self.cache,'fetch',return_value=b'<html>maintenance</html>'), self.assertRaises(ValueError):
            self.cache.download('Sony - PlayStation','redump')
        self.assertEqual(self.cache.load('Sony - PlayStation','redump').provenance['sha256'],catalog.provenance['sha256'])
        with self.assertRaises(ValueError):
            self.cache.import_bytes('Sony - PlayStation','redump',dat('Nintendo - Game Boy Advance','<game name="Wrong"/>'))
        with self.assertRaises(ValueError):
            self.cache.fetch('https://example.com/unofficial.dat')

    def test_cache_tampering_and_xml_entities_are_refused(self):
        catalog = self.cache.import_bytes('Sony - PlayStation','redump',dat('Sony - PlayStation','<game id="1" name="Example"><serial>TEST</serial></game>'))
        (self.cache.directory/(catalog.provenance['sha256']+'.dat')).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.cache.load('Sony - PlayStation','redump')
        with self.assertRaises(ValueError):
            self.cache.import_bytes('Sony - PlayStation','redump',b'<!DOCTYPE x [<!ENTITY x "expand">]><datafile/>')

    def test_filename_serial_annotations_and_libretro_escaped_titles(self):
        catalog = self.cache.import_bytes('Sony - PlayStation','redump',dat('Sony - PlayStation',
            '<game id="1" name="Rock &amp; Roll (USA)"><serial>SLUS-12345</serial></game>'))
        self.assertEqual(catalog.search('Rock _ Roll (USA)')[0][0]['redump_id'],'1')
        self.assertEqual(catalog.search('Rock & Roll (USA) (SLUS-12345)')[0][0]['redump_id'],'1')

    def test_bulk_standard_pack_selects_console_and_preferred_variant(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            for variant,serial in [('Headerless','NES-GOOD'),('Headered','NES-OTHER')]:
                z.writestr(variant+'.dat',dat('Nintendo - Nintendo Entertainment System ('+variant+')',
                    '<game id="1" name="Example (USA)"><serial>'+serial+'</serial></game>'))
            z.writestr('gba.dat',dat('Nintendo - Game Boy Advance','<game id="1" name="Wrong"><serial>WRONG</serial></game>'))
        catalog = self.cache.import_bytes('Nintendo - Nintendo Entertainment System','no-intro',buffer.getvalue(),'standard.zip')
        self.assertEqual(catalog.entries[0]['serials'],['NES-GOOD'])

    def test_nes_clean_date_publisher_region_query(self):
        catalog = self.cache.import_bytes('Nintendo - Nintendo Entertainment System','no-intro',
            dat('Nintendo - Nintendo Entertainment System (Headerless)',
                '<game id="1" name="10-Yard Fight (Japan) (En)"><serial>HVC-TY</serial></game>'))
        self.assertEqual(catalog.search('10 Yard Fight (1985-08-30)(Irem)(JP)')[0][0]['redump_id'],'1')


if __name__=='__main__':
    unittest.main()
