# tests/unit/test_geo_parse.py
from backend.normalization.geo_parse import parse_geographic_scope


def test_signal_phrase_abbreviation_list():
    result = parse_geographic_scope(
        "The recalled product was distributed to the following states: MD, VA"
    )
    assert result.parse_status == "parsed"
    assert result.is_nationwide is False
    assert result.state_codes == ("MD", "VA")


def test_domestic_foreign_split():
    result = parse_geographic_scope(
        "Domestic: AZ, CA, CO, HI, NJ, OR, TX, WA. Foreign: Not applicable."
    )
    assert result.state_codes == ("AZ", "CA", "CO", "HI", "NJ", "OR", "TX", "WA")


def test_single_bare_abbreviation():
    result = parse_geographic_scope("Distribute in HI.")
    assert result.state_codes == ("HI",)


def test_nationwide_language_sets_flag_not_state_list():
    result = parse_geographic_scope("Nationwide.")
    assert result.is_nationwide is True
    assert result.parse_status == "parsed"
    assert result.state_codes == ()


def test_nationwide_takes_priority_over_incidental_country_mentions():
    # Real record: contains "nationwide" plus a long list of foreign
    # countries, one of which ("Georgia") is also a US state name. The
    # nationwide check must short-circuit before that gets misread.
    result = parse_geographic_scope(
        "Nationwide in the United States, including American Samoa. "
        "International distribution to consumers in: France, Georgia, Germany."
    )
    assert result.is_nationwide is True
    assert result.state_codes == ()


def test_or_abbreviation_matches_only_when_standalone_caps():
    result = parse_geographic_scope("Distributed in OR and WA.")
    assert result.state_codes == ("OR", "WA")


def test_or_as_ordinary_word_is_not_misread_as_oregon():
    # Real record from the data: lowercase "or" in ordinary prose, no
    # abbreviation-list context at all.
    result = parse_geographic_scope(
        "Product was distributed to 11 consignees across California and "
        "Nevada. No foreign or institution distribution."
    )
    assert "OR" not in result.state_codes
    assert result.state_codes == ("CA", "NV")


def test_or_as_ordinary_word_alongside_a_real_oregon_mention():
    # Real record: the full word "Oregon" (a genuine state) and the
    # ordinary word "or" both appear. Only the former should count.
    result = parse_geographic_scope(
        "Product was distributed to 3 retail consignees in California, "
        "Oregon and Connecticut. No schools or institutional distribution."
    )
    assert result.state_codes == ("CA", "CT", "OR")


def test_washington_dc_is_not_read_as_washington_state():
    result = parse_geographic_scope("Washington DC, DE, GA, MD, NC, NJ, NY, PA, SC, VA.")
    assert result.state_codes == ("DC", "DE", "GA", "MD", "NC", "NJ", "NY", "PA", "SC", "VA")
    assert "WA" not in result.state_codes


def test_washington_dc_and_real_washington_state_both_present():
    result = parse_geographic_scope(
        "Product was shipped to the following states: CT, Washington DC, WA."
    )
    assert "DC" in result.state_codes
    assert "WA" in result.state_codes


def test_full_state_names_bare_list():
    result = parse_geographic_scope("Distributed in Oregon and Washington")
    assert result.state_codes == ("OR", "WA")


def test_unrecognizable_free_text_is_unparsed_not_guessed():
    result = parse_geographic_scope(
        "Products are sold directly to consumers via firm's online website."
    )
    assert result.parse_status == "unparsed"
    assert result.is_nationwide is False
    assert result.state_codes == ()


def test_empty_scope_is_unparsed():
    result = parse_geographic_scope(None)
    assert result.parse_status == "unparsed"
    assert result.state_codes == ()
