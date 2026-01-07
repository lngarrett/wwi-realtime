"""Tests for named entity extraction."""

import pytest

from wwi_realtime.media.entities import (
    Entity,
    EntityType,
    extract_persons,
    extract_locations,
    extract_military_units,
    extract_weapons,
    extract_ships,
    extract_all_entities,
    get_entity_summary,
    get_context,
)


class TestExtractPersons:
    """Tests for person extraction."""

    def test_extract_person_with_rank(self):
        """Test extracting person with military rank."""
        text = "Private John Smith reported for duty."
        persons = extract_persons(text)

        assert len(persons) == 1
        assert "Private John Smith" in persons[0].text
        assert persons[0].entity_type == EntityType.PERSON

    def test_extract_general(self):
        """Test extracting general."""
        text = "General Haig ordered the advance."
        persons = extract_persons(text)

        assert len(persons) == 1
        assert "General Haig" in persons[0].text

    def test_extract_german_rank(self):
        """Test extracting German rank."""
        text = "Leutnant Mueller led the patrol."
        persons = extract_persons(text)

        assert len(persons) == 1
        assert "Leutnant Mueller" in persons[0].text

    def test_extract_multiple_persons(self):
        """Test extracting multiple persons."""
        text = "Captain Jones met with Major Brown to discuss tactics."
        persons = extract_persons(text)

        assert len(persons) == 2
        names = [p.text for p in persons]
        assert any("Jones" in n for n in names)
        assert any("Brown" in n for n in names)

    def test_extract_person_from_attribution(self):
        """Test extracting person from quote attribution."""
        text = 'The message said Churchill was unavailable.'
        persons = extract_persons(text)

        assert len(persons) >= 1
        assert any("Churchill" in p.text for p in persons)


class TestExtractLocations:
    """Tests for location extraction."""

    def test_extract_known_location(self):
        """Test extracting known WWI location."""
        text = "The battle at Verdun continued for months."
        locations = extract_locations(text)

        assert len(locations) == 1
        assert locations[0].text == "Verdun"
        assert locations[0].entity_type == EntityType.LOCATION

    def test_extract_location_with_preposition(self):
        """Test extracting location after preposition."""
        text = "The troops marched near Amiens."
        locations = extract_locations(text)

        assert len(locations) >= 1
        assert any("Amiens" in loc.text for loc in locations)

    def test_extract_multiple_locations(self):
        """Test extracting multiple locations."""
        text = "Fighting spread from Ypres to the Somme."
        locations = extract_locations(text)

        assert len(locations) >= 2
        location_texts = [loc.text.lower() for loc in locations]
        assert any("ypres" in t for t in location_texts)
        assert any("somme" in t for t in location_texts)

    def test_extract_eastern_front_location(self):
        """Test extracting Eastern Front location."""
        text = "The battle at Tannenberg was decisive."
        locations = extract_locations(text)

        assert len(locations) == 1
        assert "Tannenberg" in locations[0].text


class TestExtractMilitaryUnits:
    """Tests for military unit extraction."""

    def test_extract_numbered_division(self):
        """Test extracting numbered division."""
        text = "The 1st Division advanced on the left flank."
        units = extract_military_units(text)

        assert len(units) == 1
        assert "1st Division" in units[0].text
        assert units[0].entity_type == EntityType.MILITARY_UNIT

    def test_extract_regiment(self):
        """Test extracting regiment."""
        text = "The 42nd Regiment held the line."
        units = extract_military_units(text)

        assert len(units) == 1
        assert "Regiment" in units[0].text

    def test_extract_bef(self):
        """Test extracting BEF."""
        text = "The BEF landed in France in August."
        units = extract_military_units(text)

        assert len(units) == 1
        assert "BEF" in units[0].text

    def test_extract_named_unit(self):
        """Test extracting named unit like Guards."""
        text = "The Royal Scots advanced through the village."
        units = extract_military_units(text)

        assert len(units) >= 1


class TestExtractWeapons:
    """Tests for weapon extraction."""

    def test_extract_machine_gun(self):
        """Test extracting machine gun."""
        text = "The machine gun nest was destroyed."
        weapons = extract_weapons(text)

        assert len(weapons) == 1
        assert "machine gun" in weapons[0].text.lower()
        assert weapons[0].entity_type == EntityType.WEAPON

    def test_extract_artillery(self):
        """Test extracting artillery."""
        text = "Heavy artillery pounded the trenches."
        weapons = extract_weapons(text)

        assert len(weapons) == 1
        assert "artillery" in weapons[0].text.lower()

    def test_extract_gas(self):
        """Test extracting gas weapon."""
        text = "They used mustard gas in the attack."
        weapons = extract_weapons(text)

        assert len(weapons) >= 1
        assert any("gas" in w.text.lower() for w in weapons)


class TestExtractShips:
    """Tests for ship extraction."""

    def test_extract_hms_ship(self):
        """Test extracting HMS ship."""
        text = "HMS Dreadnought led the fleet."
        ships = extract_ships(text)

        assert len(ships) == 1
        assert "HMS Dreadnought" in ships[0].text
        assert ships[0].entity_type == EntityType.SHIP

    def test_extract_u_boat(self):
        """Test extracting U-boat."""
        text = "U-20 torpedoed the liner."
        ships = extract_ships(text)

        assert len(ships) == 1
        assert "U-20" in ships[0].text

    def test_extract_german_ship(self):
        """Test extracting German ship."""
        text = "SMS Bayern was damaged at Jutland."
        ships = extract_ships(text)

        assert len(ships) == 1
        assert "SMS Bayern" in ships[0].text


class TestGetContext:
    """Tests for context extraction."""

    def test_get_context_middle(self):
        """Test getting context from middle of text."""
        text = "The quick brown fox jumps over the lazy dog."
        context = get_context(text, 16, 19, window=10)

        assert "fox" in context
        assert len(context) <= 30

    def test_get_context_start(self):
        """Test getting context at start of text."""
        text = "Fox jumps over the lazy dog."
        context = get_context(text, 0, 3, window=10)

        assert "Fox" in context


class TestExtractAllEntities:
    """Tests for full entity extraction."""

    def test_extract_all_from_paragraph(self):
        """Test extracting all entity types from a paragraph."""
        text = """
        General Haig ordered the 1st Division to advance on Verdun.
        Heavy artillery supported the attack as HMS Iron Duke
        provided naval support. The machine gun fire was intense.
        """
        entities = extract_all_entities(text)

        assert EntityType.PERSON in entities
        assert EntityType.LOCATION in entities
        assert EntityType.MILITARY_UNIT in entities
        assert EntityType.WEAPON in entities
        assert EntityType.SHIP in entities

        # Should find specific entities
        person_texts = [e.text for e in entities[EntityType.PERSON]]
        assert any("Haig" in t for t in person_texts)

        location_texts = [e.text for e in entities[EntityType.LOCATION]]
        assert any("Verdun" in t for t in location_texts)


class TestGetEntitySummary:
    """Tests for entity summary."""

    def test_summary_structure(self):
        """Test summary has correct structure."""
        entities = {
            EntityType.PERSON: [
                Entity("General Haig", EntityType.PERSON, 0, 12),
                Entity("General Haig", EntityType.PERSON, 50, 62),  # Duplicate
            ],
            EntityType.LOCATION: [
                Entity("Verdun", EntityType.LOCATION, 20, 26),
            ],
            EntityType.MILITARY_UNIT: [],
            EntityType.WEAPON: [],
            EntityType.SHIP: [],
        }

        summary = get_entity_summary(entities)

        assert "person" in summary
        assert summary["person"]["count"] == 2
        assert summary["person"]["unique"] == 1  # Deduped

        assert "location" in summary
        assert summary["location"]["count"] == 1

    def test_summary_limits_values(self):
        """Test summary limits values to 10."""
        entities = {
            EntityType.LOCATION: [
                Entity(f"Location{i}", EntityType.LOCATION, 0, 10)
                for i in range(20)
            ],
            EntityType.PERSON: [],
            EntityType.MILITARY_UNIT: [],
            EntityType.WEAPON: [],
            EntityType.SHIP: [],
        }

        summary = get_entity_summary(entities)

        assert len(summary["location"]["values"]) <= 10
