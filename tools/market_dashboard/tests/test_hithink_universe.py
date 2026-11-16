"""Version pinning and explicit identity checks for the Hithink universe."""
from dataclasses import replace
import copy
import json
from pathlib import Path
import unittest

from tools.market_dashboard.hithink_cli import SectorDefinition
from tools.market_dashboard.hithink_universe import (
    build_universe, catalog_diff, load_catalog_fixture, UniverseError, UniverseChangedError,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / 'tools/market_dashboard/fixtures/hithink'


class UniverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.industries = load_catalog_fixture(FIXTURES / 'catalog-industry.json')
        cls.concepts = load_catalog_fixture(FIXTURES / 'catalog-concept.json')
        cls.config = json.loads((ROOT / 'config/hithink-core-concepts.json').read_text())

    def build(self, industries=None, concepts=None, config=None):
        return build_universe(self.industries if industries is None else industries,
                              self.concepts if concepts is None else concepts,
                              self.config if config is None else config)

    def test_complete_versioned_catalog_and_primary_selection(self):
        universe = self.build()
        self.assertEqual(universe.version, 'sector-universe-ths-v1')
        self.assertEqual(len(self.industries), 320)
        self.assertEqual(len(universe.industries), 90)
        self.assertTrue(all(row.code.startswith('881') for row in universe.industries))
        self.assertFalse(any(row.code.startswith('884') for row in universe.industries))
        self.assertEqual(len(universe.concepts), 390)
        self.assertEqual(universe, self.build(tuple(reversed(self.industries)), tuple(reversed(self.concepts))))

    def test_all_core_intents_have_exact_unique_provider_identities(self):
        universe = self.build()
        old = json.loads((ROOT / 'config/market-concepts.json').read_text())
        mappings = self.config['mappings']
        self.assertEqual([row['legacyId'] for row in mappings], old['coreIds'])
        self.assertEqual(len(universe.core_concepts), 25)
        self.assertEqual(len({row.code for row in universe.core_concepts}), 25)
        concepts = {row.code: row.name for row in universe.concepts}
        for mapping in mappings:
            self.assertEqual(concepts[mapping['code']], mapping['name'])
            self.assertTrue(mapping['rationale'].strip())
            self.assertIn(mapping['relationship'], ('same_research_theme', 'scope_changed'))

    def test_duplicate_ids_and_names_fail_including_excluded_subindustries(self):
        for rows in (self.industries + (self.industries[-1],),
                     self.industries + (replace(self.industries[-1], code='884999.TI'),)):
            with self.assertRaises(UniverseError):
                self.build(industries=rows)
        with self.assertRaises(UniverseError):
            self.build(concepts=self.concepts + (replace(self.concepts[-1], code='886999.TI'),))

    def test_catalog_changes_are_explicit_deterministic_diff(self):
        added = SectorDefinition('887999.TI', '新增概念测试', 'cn_concept')
        changed = self.concepts[1:] + (added,)
        expected = catalog_diff(self.concepts, changed)
        self.assertEqual(expected.added, (added,))
        self.assertEqual(expected.removed, (self.concepts[0],))
        with self.assertRaises(UniverseChangedError) as caught:
            self.build(concepts=tuple(reversed(changed)))
        self.assertEqual(caught.exception.diff, expected)
        renamed = (replace(self.concepts[0], name='改名概念测试'),) + self.concepts[1:]
        with self.assertRaises(UniverseChangedError) as caught:
            self.build(concepts=renamed)
        self.assertEqual(len(caught.exception.diff.renamed), 1)

    def test_primary_catalog_removal_never_silently_updates_version(self):
        with self.assertRaises(UniverseChangedError):
            self.build(industries=self.industries[1:])

    def test_unresolved_duplicate_missing_or_wrong_name_core_fails(self):
        variants = []
        for field, value in [('code', None), ('code', '886999.TI'), ('name', '模糊候选'), ('relationship', 'unresolved')]:
            config = copy.deepcopy(self.config)
            config['mappings'][0][field] = value
            variants.append(config)
        config = copy.deepcopy(self.config)
        config['mappings'][1] = copy.deepcopy(config['mappings'][0])
        variants.append(config)
        config = copy.deepcopy(self.config)
        config['mappings'].pop()
        variants.append(config)
        for config in variants:
            with self.subTest(config=config['mappings'][0]):
                with self.assertRaises(UniverseError):
                    self.build(config=config)

    def test_wrong_tag_code_or_empty_name_rejected(self):
        for row in (replace(self.concepts[0], tag='industry'),
                    replace(self.concepts[0], code='000001.SH'),
                    replace(self.concepts[0], name=' ')):
            with self.assertRaises(UniverseError):
                self.build(concepts=(row,) + self.concepts[1:])


if __name__ == '__main__':
    unittest.main()
