# MCP servers for term lookups

Two small servers that let an AI agent look up standard terms while it cleans or documents a
dataset. They speak the Model Context Protocol (MCP), so any agent that can use MCP tools can
call them.

| Server | What it searches | Tools |
| --- | --- | --- |
| [`crop_ontology_server.py`](crop_ontology_server.py) | Traits and variables of [Crop Ontology](https://cropontology.org), from a local database of 37 crops | `search_traits`, `get_scale_and_synonyms`, `get_variable_info` |
| [`agrovoc_server.py`](agrovoc_server.py) | Concepts of FAO's [AGROVOC](https://www.fao.org/agrovoc/), through its public REST API | `search_agrovoc`, `get_concept_details`, `get_broader_concepts`, `get_narrower_concepts`, `get_related_concepts`, `get_top_concepts` |

CIP hosts a copy of each, which the data-cleaning skill uses by default:

- Crop Ontology: `https://CropOntology.fastmcp.app/mcp`
- AGROVOC: `https://agrovoc.fastmcp.app/mcp`

## Running them yourself

```bash
pip install -r mcp_servers/requirements.txt
```

**Crop Ontology.** The server reads a SQLite database that is not kept in this repository.
Build it once; this downloads the trait dictionary of each crop from cropontology.org and
takes about a minute:

```bash
python mcp_servers/build_crop_ontology_db.py
```

Then start the server, over stdio or over HTTP:

```bash
python mcp_servers/crop_ontology_server.py
fastmcp run mcp_servers/crop_ontology_server.py --transport http --port 8000
```

**AGROVOC.** It needs no database, only internet access:

```bash
python mcp_servers/agrovoc_server.py
fastmcp run mcp_servers/agrovoc_server.py --transport http --port 8001
```

## What to expect

- The build script lists 39 Crop Ontology reports. In November 2026, 37 of them loaded (about
  8,200 variables); "Barley Trait POLAPGEN Ontology" and "Sainfoin" did not.
- `search_traits` matches the search text inside the trait name or its synonyms, within one
  crop. It does not rank results and does not understand meaning: "tuber weight" finds
  nothing if the ontology says "weight of tubers". The agent usually has to try several
  wordings.
- `get_scale_and_synonyms` returns the first 10 categories of a scale. The scales of 37
  variables are longer and come back cut.
- `search_agrovoc` passes the query to AGROVOC as written; `*` is a wildcard.
- Both servers suggest a term. A person should confirm each mapping before it is recorded.

The terms belong to Crop Ontology and to FAO and are served under their own licences.
