"""The Crop Ontology MCP server answers its three tools from a small database built here."""

import asyncio
import importlib.util
import sqlite3
from pathlib import Path

import pytest

fastmcp = pytest.importorskip("fastmcp")

SERVER = Path(__file__).parents[1] / "mcp_servers" / "crop_ontology_server.py"
COLUMNS = ["crop", "trait_name", "trait_description", "trait_synonyms", "variable_name", "variable_synonyms", "scale_class"]
CATEGORIES = [f"category_{i}" for i in range(1, 11)]
ROWS = [
    ("Potato", "Plant growth habit", "Habit of the plant", "habit", "PlGwht_Et_1to6", "HABIT, PGH", "Ordinal", "1 = Erect", "2 = Semi-erect"),
    ("Potato", "Tuber yield", "Weight of tubers per area", "yield", "TbYld_Cp_tha", "YIELD", "Numerical", None, None),
    ("Wheat", "Grain yield", "Weight of grain per area", "yield", "GY_Calc_tha", "GYLD", "Numerical", None, None),
]


@pytest.fixture
def server(tmp_path, monkeypatch):
    db = tmp_path / "crop_ontology_excel.db"
    names = COLUMNS + CATEGORIES
    with sqlite3.connect(db) as conn:
        conn.execute(f"CREATE TABLE ontology ({', '.join(names)})")
        for row in ROWS:
            padded = row + (None,) * (len(names) - len(row))
            conn.execute(f"INSERT INTO ontology VALUES ({', '.join('?' * len(names))})", padded)
    spec = importlib.util.spec_from_file_location("crop_ontology_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", db)
    return module.mcp


def call(server, tool: str, arguments: dict) -> dict:
    async def run():
        async with fastmcp.Client(server) as client:
            return (await client.call_tool(tool, arguments)).structured_content

    return asyncio.run(run())


def test_search_stays_within_the_crop_and_matches_synonyms(server):
    found = call(server, "search_traits", {"crop_name": "potato", "query": "Yield"})["results"]
    assert [r["variable_name"] for r in found] == ["TbYld_Cp_tha"]


def test_scale_lists_only_the_categories_that_exist(server):
    scale = call(server, "get_scale_and_synonyms", {"crop_name": "Potato", "variable_name": "PlGwht_Et_1to6"})
    assert scale == {"scale_class": "Ordinal", "scale_categories": ["1 = Erect", "2 = Semi-erect"], "variable_synonyms": "HABIT, PGH"}


def test_variable_info_returns_every_field_and_blanks_as_null(server):
    info = call(server, "get_variable_info", {"crop_name": "Wheat", "variable_name": "GY_Calc_tha"})
    assert info["trait_name"] == "Grain yield"
    assert info["category_1"] is None


def test_unknown_variable_is_an_error(server):
    with pytest.raises(Exception, match="not found"):
        call(server, "get_variable_info", {"crop_name": "Potato", "variable_name": "nope"})
