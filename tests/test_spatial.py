"""Tables 3.2.3.1-B/-C/-D and 3.2.3.7, cell by cell. Face-level behaviour is in test_courtyard_commons.py."""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from codesheet.table_3231 import permitted_upo_sprinklered, permitted_upo_unsprinklered, exposing_face_requirements


def test_table_d_spot_values():
    # exact cells from Table 3.2.3.1.-D
    assert permitted_upo_sprinklered(10, 2.0)[0] == 42
    assert permitted_upo_sprinklered(150, 4)[0] == 30
    assert permitted_upo_sprinklered(500, 9)[0] == 100
    # interpolation on LD within the ≥150 row: 4.6 m between 30 (4 m) and 40 (5 m)
    assert permitted_upo_sprinklered(298, 4.6)[0] == 36.0
    # interpolation on area: 45 m² at LD 3 m between the 40 (40 %) and 50 (36 %) rows
    assert permitted_upo_sprinklered(45, 3.0)[0] == 38.0
    assert permitted_upo_sprinklered(20, 0)[0] == 0


def test_table_3237_bands():
    assert exposing_face_requirements(8)[:3] == (60, "noncombustible", "noncombustible")
    assert exposing_face_requirements(10)[:3] == (60, "noncombustible", "noncombustible")
    assert exposing_face_requirements(20)[:3] == (60, "combustible, EMTC or noncombustible", "noncombustible")
    assert exposing_face_requirements(36)[:3] == (45, "combustible, EMTC or noncombustible", "noncombustible")
    assert exposing_face_requirements(75)[:3] == (45, "combustible, EMTC or noncombustible", "combustible or noncombustible")
    assert exposing_face_requirements(100)[0] == 0


def test_unsprinklered_tables_spot_values():
    # Table -B, 30 m² face, ratio <3:1: 0, 7, 8, 11, 15, 20, 35, 56, 83, 100 at LD 0,1.2,1.5,2,2.5,3,4,5,6,7
    assert permitted_upo_unsprinklered(30, 3.0, 6, 5, "C")[0] == 20
    assert permitted_upo_unsprinklered(30, 5.0, 6, 5, "C")[0] == 56
    # ratio sub-row: a long low face (>10:1) gets more at the same area/LD
    assert permitted_upo_unsprinklered(30, 3.0, 30, 1, "C")[0] > 20
    # Table -C (Group E) is tighter than -B at the same cell
    assert permitted_upo_unsprinklered(30, 3.0, 6, 5, "E")[0] < permitted_upo_unsprinklered(30, 3.0, 6, 5, "C")[0]
    # sprinklered Table -D permits roughly double the unsprinklered -B value
    assert permitted_upo_sprinklered(30, 3.0)[0] >= 2 * permitted_upo_unsprinklered(30, 3.0, 6, 5, "C")[0] - 2
