"""MCP server that searches the Crop Ontology traits and variables of many crops.

It reads a local SQLite database. Build it first with `build_crop_ontology_db.py`, then:

    python crop_ontology_server.py
"""

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Dict, List

import pandas as pd
from fastmcp import Context, FastMCP
from fastmcp.prompts.prompt import Message
from pydantic import BaseModel, ConfigDict, Field

# The SQLite database written by build_crop_ontology_db.py.
DB_PATH = Path(__file__).parent / "crop_ontology_excel.db"


# --- Lifespan Context: Connect to the SQLite DB on startup ---
class AppContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    conn: sqlite3.Connection


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Connect to the SQLite database on server startup and close it on shutdown."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database file not found at: {DB_PATH}. "
            f"Run build_crop_ontology_db.py first."
        )

    conn = sqlite3.connect(DB_PATH)
    try:
        print(f"Successfully connected to database: {DB_PATH}")
        yield AppContext(conn=conn)
    finally:
        conn.close()
        print("Database connection closed.")


mcp = FastMCP(
    "CropOntologyMCP",
    lifespan=app_lifespan,
    instructions="This server can search for traits and variables within multiple crop ontologies.",
)


# --- Pydantic Models for Structured Tool Outputs ---
class TraitInfo(BaseModel):
    """Represents a single trait search result."""

    trait_name: str
    trait_description: str
    variable_name: str


class TraitSearchResults(BaseModel):
    """Container for a list of trait search results."""

    results: List[TraitInfo]


class ScaleInfo(BaseModel):
    """Contains scale and synonym information for a variable."""

    scale_class: str
    scale_categories: List[str]
    variable_synonyms: str


# --- Tools ---
@mcp.tool()
def search_traits(
    ctx: Context,
    crop_name: Annotated[
        str,
        Field(description="The name of the crop to search (e.g., 'Potato', 'Wheat')."),
    ],
    query: Annotated[
        str, Field(description="The search term for trait names or synonyms.")
    ],
    max_results: Annotated[
        int, Field(description="The maximum number of results to return.", default=10)
    ] = 10,
) -> TraitSearchResults:
    """Search a specific crop's ontology for traits by trait name or synonyms."""
    # Use a fresh SQLite connection per request to avoid closed-connection issues.
    sql_query = """
        SELECT trait_name, trait_description, variable_name
        FROM ontology
        WHERE LOWER(crop) = ? AND (LOWER(trait_name) LIKE ? OR LOWER(trait_synonyms) LIKE ?)
        LIMIT ?
    """
    params = (
        crop_name.lower(),
        f"%{query.lower()}%",
        f"%{query.lower()}%",
        max_results,
    )

    with sqlite3.connect(DB_PATH) as conn:
        results_df = pd.read_sql_query(sql_query, conn, params=params)
    records = results_df.to_dict(orient="records")

    return TraitSearchResults(results=[TraitInfo.model_validate(r) for r in records])


@mcp.tool()
def get_scale_and_synonyms(
    ctx: Context,
    crop_name: Annotated[str, Field(description="The specific crop to query.")],
    variable_name: Annotated[
        str, Field(description="The specific variable name to look up.")
    ],
) -> ScaleInfo:
    """Retrieve the scale class, categories, and synonyms for a given variable name in a crop."""
    # The categories of a scale are stored in separate columns (category_1 ... category_10).
    category_cols = ", ".join([f"category_{i}" for i in range(1, 11)])
    sql_query = f"""
        SELECT scale_class, variable_synonyms, {category_cols}
        FROM ontology
        WHERE LOWER(crop) = ? AND variable_name = ?
    """
    params = (crop_name.lower(), variable_name)

    with sqlite3.connect(DB_PATH) as conn:
        results_df = pd.read_sql_query(sql_query, conn, params=params)

    if results_df.empty:
        raise ValueError(
            f"Variable '{variable_name}' not found in the '{crop_name}' ontology."
        )

    record = results_df.iloc[0]

    # Build the category list from the separate columns.
    categories = []
    for i in range(1, 11):
        col_name = f"category_{i}"
        if col_name in record and pd.notna(record[col_name]):
            categories.append(str(record[col_name]))

    scale_class_str = record.get("scale_class")
    variable_synonyms_str = record.get("variable_synonyms")

    return ScaleInfo(
        scale_class=str(scale_class_str) if pd.notna(scale_class_str) else "",
        scale_categories=categories,
        variable_synonyms=str(variable_synonyms_str)
        if pd.notna(variable_synonyms_str)
        else "",
    )


@mcp.tool()
def get_variable_info(
    ctx: Context,
    crop_name: Annotated[str, Field(description="The specific crop to query.")],
    variable_name: Annotated[
        str, Field(description="The specific variable name to look up.")
    ],
) -> Dict[str, Any]:
    """Return all available metadata fields for a given variable name in a crop."""
    sql_query = "SELECT * FROM ontology WHERE LOWER(crop) = ? AND variable_name = ?"
    params = (crop_name.lower(), variable_name)

    with sqlite3.connect(DB_PATH) as conn:
        results_df = pd.read_sql_query(sql_query, conn, params=params)

    if results_df.empty:
        raise ValueError(
            f"Variable '{variable_name}' not found in the '{crop_name}' ontology."
        )

    record = results_df.iloc[0].to_dict()
    # Clean up NaN/None values for clean JSON output
    serializable_record = {
        k: (v if pd.notna(v) and v != "" else None) for k, v in record.items()
    }
    return serializable_record


# --- Prompt Templates ---
@mcp.prompt(
    name="prompt_search_traits",
    description="Guides the LLM to search for traits in a specific crop.",
)
def prompt_search_traits(
    crop_name: Annotated[str, Field(description="The name of the crop.")],
    query: Annotated[str, Field(description="The search term for the trait.")],
) -> tuple:
    return (
        Message(
            f"I can search {crop_name} traits matching '{query}'.", role="assistant"
        ),
        Message(
            f"Please call `search_traits` with crop_name='{crop_name}' and query='{query}'.",
            role="user",
        ),
    )


@mcp.prompt(
    name="prompt_get_variable_info",
    description="Guides the LLM to fetch full metadata for a variable.",
)
def prompt_get_variable_info(
    crop_name: Annotated[str, Field(description="The name of the crop.")],
    variable_name: Annotated[str, Field(description="The variable name to look up.")],
) -> tuple:
    return (
        Message(
            f"I can retrieve all information for variable '{variable_name}' in {crop_name}.",
            role="assistant",
        ),
        Message(
            f"Call `get_variable_info` with crop_name='{crop_name}' and variable_name='{variable_name}'.",
            role="user",
        ),
    )


# --- Run Server ---
if __name__ == "__main__":
    print("Starting Crop Ontology MCP server...")
    mcp.run()
