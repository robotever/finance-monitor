"""Pinned Hithink catalog identities, independent of former Wind scores.

The normalized fixtures are the reviewed v1 catalog baseline. A provider
addition, removal or rename raises a deterministic diff: a refresh must be
reviewed and versioned explicitly, never silently folded into v1.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .hithink_cli import SectorDefinition

UNIVERSE_VERSION = 'sector-universe-ths-v1'
_FIXTURES = Path(__file__).parent / 'fixtures' / 'hithink'
_PRIMARY = re.compile(r'^881[0-9]{3}\.TI$')
_INDUSTRY = re.compile(r'^(?:881|884)[0-9]{3}\.TI$')
_CONCEPT = re.compile(r'^[0-9]{6}\.TI$')


class UniverseError(ValueError):
    def __init__(self, code='INVALID_SECTOR_UNIVERSE'):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CatalogDiff:
    added: tuple[SectorDefinition, ...] = ()
    removed: tuple[SectorDefinition, ...] = ()
    renamed: tuple[tuple[SectorDefinition, SectorDefinition], ...] = ()

    @property
    def changed(self):
        return bool(self.added or self.removed or self.renamed)

    def as_dict(self):
        def row(value):
            return {'code': value.code, 'name': value.name, 'tag': value.tag}
        return {'added': [row(value) for value in self.added],
                'removed': [row(value) for value in self.removed],
                'renamed': [{'before': row(before), 'after': row(after)}
                            for before, after in self.renamed]}


class UniverseChangedError(UniverseError):
    def __init__(self, diff):
        self.diff = diff
        super().__init__('SECTOR_CATALOG_CHANGED')


@dataclass(frozen=True)
class SectorUniverse:
    version: str
    industries: tuple[SectorDefinition, ...]
    concepts: tuple[SectorDefinition, ...]
    core_concepts: tuple[SectorDefinition, ...]
    catalog_digest: str

    @property
    def core_ids(self):
        return tuple(row.code for row in self.core_concepts)


def _validate_rows(rows, tag):
    pattern = _INDUSTRY if tag == 'industry' else _CONCEPT
    try:
        rows = tuple(rows)
    except TypeError:
        raise UniverseError() from None
    codes, names = set(), set()
    for row in rows:
        if (not isinstance(row, SectorDefinition) or row.tag != tag
                or not isinstance(row.code, str) or not pattern.fullmatch(row.code)
                or not isinstance(row.name, str) or not row.name.strip()
                or row.name != row.name.strip() or row.code in codes or row.name in names):
            raise UniverseError()
        codes.add(row.code)
        names.add(row.name)
    return tuple(sorted(rows, key=lambda row: row.code))


def load_catalog_fixture(path):
    """Read normalized catalog records only, with no provider response envelope."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if (set(data) != {'universeVersion', 'source', 'observedDate', 'tag', 'rows'}
                or data['universeVersion'] != UNIVERSE_VERSION or data['source'] != 'Hithink'
                or data['tag'] not in ('industry', 'cn_concept') or not isinstance(data['rows'], list)):
            raise ValueError()
        rows = []
        for row in data['rows']:
            if set(row) != {'code', 'name', 'tag'}:
                raise ValueError()
            rows.append(SectorDefinition(**row))
        return _validate_rows(rows, data['tag'])
    except (OSError, TypeError, KeyError, ValueError):
        raise UniverseError('INVALID_CATALOG_FIXTURE') from None


def catalog_diff(previous_rows, current_rows):
    """Compare exact (tag, code) identities; a name change is never a fuzzy match."""
    def indexed(rows):
        rows = tuple(rows)
        result = {}
        for tag in ('industry', 'cn_concept'):
            for row in _validate_rows([row for row in rows if isinstance(row, SectorDefinition) and row.tag == tag], tag):
                result[(row.tag, row.code)] = row
        if len(result) != len(rows):
            raise UniverseError()
        return result
    before, after = indexed(previous_rows), indexed(current_rows)
    return CatalogDiff(
        tuple(after[key] for key in sorted(after.keys() - before.keys())),
        tuple(before[key] for key in sorted(before.keys() - after.keys())),
        tuple((before[key], after[key]) for key in sorted(before.keys() & after.keys())
              if before[key].name != after[key].name),
    )


def build_universe(industry_rows, concept_rows, core_config) -> SectorUniverse:
    industries = _validate_rows(industry_rows, 'industry')
    concepts = _validate_rows(concept_rows, 'cn_concept')
    baseline = (load_catalog_fixture(_FIXTURES / 'catalog-industry.json')
                + load_catalog_fixture(_FIXTURES / 'catalog-concept.json'))
    diff = catalog_diff(baseline, industries + concepts)
    if diff.changed:
        raise UniverseChangedError(diff)
    primary = tuple(row for row in industries if _PRIMARY.fullmatch(row.code))
    if len(primary) != 90:
        raise UniverseError('INVALID_PRIMARY_INDUSTRY_COUNT')
    if (not isinstance(core_config, dict) or core_config.get('universeVersion') != UNIVERSE_VERSION
            or core_config.get('mappingVersion') != 'hithink-core-intents-v1'
            or core_config.get('source') != 'Hithink'):
        raise UniverseError('INVALID_CORE_MAPPING')
    mappings = core_config.get('mappings')
    if not isinstance(mappings, list) or len(mappings) != 25:
        raise UniverseError('INVALID_CORE_MAPPING')
    by_code = {row.code: row for row in concepts}
    core, legacy_ids = [], set()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise UniverseError('INVALID_CORE_MAPPING')
        code, legacy = mapping.get('code'), mapping.get('legacyId')
        if (not isinstance(code, str) or code not in by_code
                or mapping.get('name') != by_code[code].name
                or not isinstance(legacy, str) or not re.fullmatch(r'\d{6,7}\.WI', legacy)
                or legacy in legacy_ids or code in {row.code for row in core}
                or mapping.get('relationship') not in ('same_research_theme', 'scope_changed')
                or mapping.get('scope') not in ('provider_defined', 'infrastructure_proxy', 'narrower_proxy', 'broader_proxy')
                or any(not isinstance(mapping.get(key), str) or not mapping[key].strip()
                       for key in ('legacyName', 'researchIntent', 'group', 'rationale'))):
            raise UniverseError('INVALID_CORE_MAPPING')
        legacy_ids.add(legacy)
        core.append(by_code[code])
    canonical = [{'code': row.code, 'name': row.name, 'tag': row.tag} for row in industries + concepts]
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':')).encode('utf-8')).hexdigest()
    return SectorUniverse(UNIVERSE_VERSION, primary, concepts, tuple(core), digest)
