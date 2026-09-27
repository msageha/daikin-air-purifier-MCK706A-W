import pytest

from daikin.protocol import (
    OP_READ,
    OP_WRITE,
    PropertyTree,
    build_read_requests,
    build_write_request,
    hex_to_ascii,
    hex_to_int,
    hex_to_temp,
)


def test_hex_to_int_little_endian():
    assert hex_to_int("3000") == 48
    assert hex_to_int("41") == 65
    assert hex_to_int("940200") == 660
    assert hex_to_int("00") == 0


def test_hex_to_int_signed():
    # 0xFFEE little-endian, two's complement -> -18
    assert hex_to_int("EEFF", signed=True) == -18
    assert hex_to_int("EEFF") == 65518


def test_hex_to_temp_half_degrees():
    assert hex_to_temp("3000") == 24.0  # 48 / 2
    assert hex_to_temp("EEFF") == -9.0  # -18 / 2
    assert hex_to_temp("B400") == 90.0  # 180 / 2


def test_hex_to_ascii_trims_nul():
    assert hex_to_ascii("413530375F4B000000") == "A507_K"
    assert hex_to_ascii("44413831") == "DA81"


# A trimmed-down sample of a real adr_0100.dgc_status response.
SAMPLE_PC = {
    "pn": "dgc_status",
    "pt": 1,
    "pch": [
        {
            "pn": "e_1002",
            "pt": 1,
            "pch": [
                {
                    "pn": "e_A002",
                    "pt": 1,
                    "pch": [{"pn": "p_01", "pt": 2, "pv": "01", "md": {"pt": "b"}}],
                },
                {
                    "pn": "e_A00B",
                    "pt": 1,
                    "pch": [
                        {"pn": "p_01", "pt": 3, "pv": "3000", "md": {"pt": "b"}},
                        {"pn": "p_02", "pt": 3, "pv": "41", "md": {"pt": "b"}},
                    ],
                },
            ],
        }
    ],
}


def test_property_tree_builds_slash_paths():
    tree = PropertyTree(SAMPLE_PC)
    assert set(tree.leaves) == {
        "e_1002/e_A002/p_01",
        "e_1002/e_A00B/p_01",
        "e_1002/e_A00B/p_02",
    }
    assert tree.leaves["e_1002/e_A00B/p_01"]["pv"] == "3000"


def test_property_tree_empty():
    assert PropertyTree({}).leaves == {}
    assert PropertyTree({"pn": "dgc_status", "pt": 1, "pch": []}).leaves == {}


def test_property_tree_pv_and_decode():
    tree = PropertyTree(SAMPLE_PC)
    assert tree.pv("e_1002/e_A002/p_01") == "01"
    assert tree.pv("nope") is None
    assert tree.decode("e_1002/e_A00B/p_01", hex_to_temp) == 24.0
    assert tree.decode("nope", hex_to_int) is None


def test_build_read_requests():
    body = build_read_requests(["/dsiot/edge.adp_i", "/dsiot/edge.adp_d"])
    assert body == {
        "requests": [
            {"op": OP_READ, "to": "/dsiot/edge.adp_i"},
            {"op": OP_READ, "to": "/dsiot/edge.adp_d"},
        ]
    }


def test_build_write_request_nests_from_leaf():
    body = build_write_request(
        "/dsiot/edge/adr_0100.dgc_status", ["e_1002", "e_A002", "p_01"], "00"
    )
    req = body["requests"][0]
    assert req["op"] == OP_WRITE
    assert req["to"] == "/dsiot/edge/adr_0100.dgc_status"
    pc = req["pc"]
    assert pc["pn"] == "dgc_status"
    e1002 = pc["pch"][0]
    assert e1002["pn"] == "e_1002"
    e_a002 = e1002["pch"][0]
    assert e_a002["pn"] == "e_A002"
    leaf = e_a002["pch"][0]
    assert leaf == {"pn": "p_01", "pt": 3, "pv": "00"}


def test_build_write_request_rejects_empty_path():
    with pytest.raises(ValueError):
        build_write_request("/dsiot/edge/adr_0100.dgc_status", [], "00")
