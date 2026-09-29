"""Table 3.1.3.1 and its notes, straight from the table. Project-level behaviour is in test_courtyard_commons.py."""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from codesheet.separations import required_frr, table_frr


def test_table_symmetry_and_values():
    assert table_frr("C", "A2") == 1 and table_frr("A2", "C") == 1
    assert table_frr("C", "E") == 2 and table_frr("D", "E") is None and table_frr("C", "F1") == "X"
    assert table_frr("C", "C") is None


def test_note3_two_hours_under_3_2_2_51():
    assert required_frr("C", "A2", "3.2.2.51")[0] == 2.0
    assert required_frr("C", "A2", "3.2.2.49")[0] == 1.0


def test_note4_two_hours_under_3_2_2_60():
    assert required_frr("D", "A2", "3.2.2.60")[0] == 2.0
    assert required_frr("D", "A2", "3.2.2.51")[0] == 1.0


def test_prohibited_and_unrequired_pairs():
    assert required_frr("C", "F1", None)[0] == "X"
    assert required_frr("D", "E", None) == (None, "Table 3.1.3.1 shows no requirement (—) for this pair")
