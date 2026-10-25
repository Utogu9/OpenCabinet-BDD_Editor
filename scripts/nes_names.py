"""Conservative conversion of date/publisher/region NES artwork names."""
import re

TOSEC = re.compile(r'^(.+?) \(((?:19|20)[0-9x?]{2}(?:-[0-9x?]{2}){0,2})\)'
                   r'\(([^()]*)\)\(([A-Z]{2}(?:-[A-Z]{2})*)\)(.*)$', re.I)
REGIONS = {'JP':'Japan', 'US':'USA', 'EU':'Europe', 'AS':'Asia', 'AU':'Australia',
           'UK':'UK', 'FR':'France', 'DE':'Germany', 'ES':'Spain', 'IT':'Italy',
           'CA':'Canada', 'BR':'Brazil', 'KR':'Korea', 'TW':'Taiwan', 'CN':'China',
           'RU':'Russia', 'NL':'Netherlands', 'SE':'Sweden'}


def convert_name(value):
    parsed = TOSEC.fullmatch(value)
    if not parsed:
        return None
    title, date, publisher, region, extra = parsed.groups()
    # Never turn hacks, translations, pirates, bad dumps or unknown annotations
    # into retail releases by discarding their square-bracket tags.
    if extra not in {'', '[!]'}:
        return None
    codes = region.upper().split('-')
    if any(code not in REGIONS for code in codes):
        return None
    return {'name': title+' ('+', '.join(REGIONS[code] for code in codes)+')',
            'date': date, 'publisher': publisher, 'policy': 'nes-tosec-clean-only-v1'}


def safe_candidates(value, metadata_index, title_index):
    from catalog_rules import metadata_candidates, tagged_title, metadata_identity
    conversion = convert_name(value)
    if not conversion:
        return [], None
    target = conversion['name']
    matches, _, _ = metadata_candidates(target, metadata_index)
    title, regions, _ = tagged_title(target)
    if len(matches) == 1:
        title = tagged_title(matches[0]['name'])[0]
    # A publisher alone is not enough to choose between retail/unlicensed,
    # prototype/revision releases. Leave those cases for review.
    alternatives = [e for e in title_index.get(title, [])
                    if regions <= tagged_title(e['name'])[1]]
    identities = {metadata_identity(e['name'])[:2] for e in alternatives}
    if len(matches) != 1 or len(identities) != 1:
        conversion['decision'] = 'no_unique_release'
        return [], conversion
    conversion['decision'] = 'unique_release'
    return matches, conversion
