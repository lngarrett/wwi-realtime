"""Named entity extraction for WWI content.

Simple regex-based NER for extracting military ranks, names, locations,
and units from WWI-era text.
"""

import re
from dataclasses import dataclass
from enum import Enum


class EntityType(Enum):
    """Types of entities we extract."""
    PERSON = "person"
    LOCATION = "location"
    MILITARY_UNIT = "unit"
    RANK = "rank"
    WEAPON = "weapon"
    SHIP = "ship"


@dataclass
class Entity:
    """An extracted named entity."""
    text: str
    entity_type: EntityType
    start: int  # Character offset
    end: int
    context: str | None = None  # Surrounding text


# Military ranks by nation
MILITARY_RANKS = {
    # British/American
    'Private', 'Corporal', 'Sergeant', 'Lieutenant', 'Captain',
    'Major', 'Colonel', 'Brigadier', 'General',
    'Field Marshal', 'Admiral', 'Commodore',
    # German
    'Gefreiter', 'Unteroffizier', 'Feldwebel', 'Leutnant', 'Hauptmann',
    'Oberst', 'Generalmajor', 'Generalleutnant',
    # French
    'Soldat', 'Caporal', 'Sergent', 'Sous-lieutenant',
    'Capitaine', 'Commandant', 'Général',
}

# Location patterns
LOCATION_INDICATORS = [
    'near', 'at', 'in', 'from', 'to', 'toward', 'towards',
    'through', 'across', 'along', 'between',
]

# WWI-specific locations
WWI_LOCATIONS = {
    # Western Front
    'Verdun', 'Somme', 'Ypres', 'Passchendaele', 'Marne',
    'Flanders', 'Artois', 'Champagne', 'Lorraine', 'Alsace',
    'Mons', 'Liège', 'Antwerp', 'Brussels', 'Paris',
    # Eastern Front
    'Tannenberg', 'Galicia', 'Warsaw', 'Przemyśl',
    # Other theaters
    'Gallipoli', 'Constantinople', 'Baghdad', 'Jerusalem',
    'Jutland', 'Dogger Bank',
}

# Military unit patterns
UNIT_PATTERNS = [
    r'\d+(?:st|nd|rd|th)\s+(?:Division|Regiment|Battalion|Brigade|Corps|Army)',
    r'(?:First|Second|Third|Fourth|Fifth)\s+Army',
    r'[A-Z][a-z]+\s+(?:Guards?|Rifles?|Fusiliers?|Highlanders?)',
    r'(?:Royal|Imperial)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?',
    r'BEF|AEF|ANZACs?',
]

# Weapon patterns
WEAPON_PATTERNS = [
    r'machine\s*gun',
    r'howitzer',
    r'artillery',
    r'rifle',
    r'bayonet',
    r'mortar',
    r'tank',
    r'gas',
    r'mustard\s*gas',
    r'chlorine',
]

# Ship patterns
SHIP_PATTERNS = [
    r'HMS\s+[A-Z][a-z]+',
    r'SMS\s+[A-Z][a-z]+',
    r'USS\s+[A-Z][a-z]+',
    r'U-\d+',
]


def extract_persons(text: str) -> list[Entity]:
    """Extract person names with military ranks.

    Looks for patterns like "Private John Smith" or "General Haig".

    Args:
        text: Text to search

    Returns:
        List of person entities
    """
    entities = []

    # Build rank pattern
    rank_pattern = '|'.join(re.escape(r) for r in MILITARY_RANKS)

    # Pattern: Rank followed by name(s)
    pattern = rf'\b({rank_pattern})\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b'

    for match in re.finditer(pattern, text):
        full_match = match.group(0)
        entities.append(Entity(
            text=full_match,
            entity_type=EntityType.PERSON,
            start=match.start(),
            end=match.end(),
            context=get_context(text, match.start(), match.end()),
        ))

    # Also look for standalone names with common indicators
    name_indicators = [
        r'(?:said|wrote|declared|reported|stated)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:said|wrote|declared)',
    ]

    for pattern in name_indicators:
        for match in re.finditer(pattern, text):
            name = match.group(1)
            # Skip if already found with rank
            if not any(name in e.text for e in entities):
                entities.append(Entity(
                    text=name,
                    entity_type=EntityType.PERSON,
                    start=match.start(1),
                    end=match.end(1),
                    context=get_context(text, match.start(), match.end()),
                ))

    return entities


def extract_locations(text: str) -> list[Entity]:
    """Extract location names.

    Args:
        text: Text to search

    Returns:
        List of location entities
    """
    entities = []

    # Known WWI locations
    for location in WWI_LOCATIONS:
        pattern = rf'\b{re.escape(location)}\b'
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entities.append(Entity(
                text=match.group(0),
                entity_type=EntityType.LOCATION,
                start=match.start(),
                end=match.end(),
                context=get_context(text, match.start(), match.end()),
            ))

    # Pattern: "near/at/in [Capitalized Place]"
    indicator_pattern = '|'.join(re.escape(i) for i in LOCATION_INDICATORS)
    pattern = rf'\b({indicator_pattern})\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b'

    for match in re.finditer(pattern, text):
        location = match.group(2)
        # Skip if already found
        if not any(location.lower() == e.text.lower() for e in entities):
            entities.append(Entity(
                text=location,
                entity_type=EntityType.LOCATION,
                start=match.start(2),
                end=match.end(2),
                context=get_context(text, match.start(), match.end()),
            ))

    return entities


def extract_military_units(text: str) -> list[Entity]:
    """Extract military unit names.

    Args:
        text: Text to search

    Returns:
        List of unit entities
    """
    entities = []

    for pattern in UNIT_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entities.append(Entity(
                text=match.group(0),
                entity_type=EntityType.MILITARY_UNIT,
                start=match.start(),
                end=match.end(),
                context=get_context(text, match.start(), match.end()),
            ))

    return entities


def extract_weapons(text: str) -> list[Entity]:
    """Extract weapon mentions.

    Args:
        text: Text to search

    Returns:
        List of weapon entities
    """
    entities = []

    for pattern in WEAPON_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entities.append(Entity(
                text=match.group(0),
                entity_type=EntityType.WEAPON,
                start=match.start(),
                end=match.end(),
                context=get_context(text, match.start(), match.end()),
            ))

    return entities


def extract_ships(text: str) -> list[Entity]:
    """Extract ship names.

    Args:
        text: Text to search

    Returns:
        List of ship entities
    """
    entities = []

    for pattern in SHIP_PATTERNS:
        for match in re.finditer(pattern, text):
            entities.append(Entity(
                text=match.group(0),
                entity_type=EntityType.SHIP,
                start=match.start(),
                end=match.end(),
                context=get_context(text, match.start(), match.end()),
            ))

    return entities


def get_context(text: str, start: int, end: int, window: int = 50) -> str:
    """Get context around an entity.

    Args:
        text: Full text
        start: Entity start position
        end: Entity end position
        window: Characters of context on each side

    Returns:
        Context string
    """
    ctx_start = max(0, start - window)
    ctx_end = min(len(text), end + window)
    return text[ctx_start:ctx_end].strip()


def extract_all_entities(text: str) -> dict[EntityType, list[Entity]]:
    """Extract all entity types from text.

    Args:
        text: Text to search

    Returns:
        Dict mapping entity types to lists of entities
    """
    return {
        EntityType.PERSON: extract_persons(text),
        EntityType.LOCATION: extract_locations(text),
        EntityType.MILITARY_UNIT: extract_military_units(text),
        EntityType.WEAPON: extract_weapons(text),
        EntityType.SHIP: extract_ships(text),
    }


def get_entity_summary(entities: dict[EntityType, list[Entity]]) -> dict:
    """Get a summary of extracted entities.

    Args:
        entities: Dict from extract_all_entities

    Returns:
        Summary dict with counts and unique values
    """
    summary = {}
    for entity_type, entity_list in entities.items():
        unique_texts = list(set(e.text for e in entity_list))
        summary[entity_type.value] = {
            'count': len(entity_list),
            'unique': len(unique_texts),
            'values': unique_texts[:10],  # Top 10
        }
    return summary
