"""MCP server that searches FAO's AGROVOC vocabulary and walks its concept hierarchy.

It calls the public AGROVOC REST API (Skosmos); it stores nothing locally.

    python agrovoc_server.py
"""
import asyncio
import httpx
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Any, AsyncIterator, Dict, List, Optional

from fastmcp import Context, FastMCP
from fastmcp.prompts.prompt import Message
from pydantic import Field

# --- Configuration ---
BASE_URL = "https://agrovoc.fao.org/browse/rest/v1"
AGROVOC_ID = "agrovoc"  # The official Skosmos ID for the AGROVOC vocabulary

# --- Custom Exception ---
class ConceptNotFoundError(Exception):
    """Custom exception for when an AGROVOC concept is not found."""
    pass

# --- Server Lifespan ---
@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[None]:
    """A manager for server startup and shutdown logic."""
    print(f"Starting up {server.name}...")
    yield
    print(f"{server.name} shutting down...")

# --- Server Initialization ---
mcp = FastMCP(
    "AgrovocMCP",
    lifespan=app_lifespan,
    instructions="A server for searching and exploring the AGROVOC vocabulary using the Skosmos API."
)

# --- Dataclasses for Structured Tool Output ---
@dataclass
class ConceptResultItem:
    """A single concept item from a search result."""
    uri: str
    prefLabel: str
    altLabel: Optional[str] = None
    lang: Optional[str] = None
    vocab: Optional[str] = None
    type: List[str] = field(default_factory=list)
    localname: Optional[str] = None
    notation: Optional[str] = None

@dataclass
class SearchResults:
    """The structured results of a search operation."""
    query: str
    item_count: int
    items: List[ConceptResultItem]

@dataclass
class ConceptInfo:
    """Represents basic info for a related concept."""
    uri: str
    prefLabel: str
    notation: Optional[str] = None
    hasChildren: Optional[bool] = None

@dataclass
class TopConceptInfo:
    """Represents a single top concept item."""
    uri: str
    label: str
    hasChildren: bool
    topConceptOf: Optional[str] = None
    notation: Optional[str] = None

@dataclass
class Label:
    lang: str
    value: str

@dataclass
class Relation:
    uri: str

@dataclass
class ConceptDetails:
    """Represents the detailed information for a single concept."""
    uri: str
    type: str
    prefLabels: List[Label] = field(default_factory=list)
    altLabels: List[Label] = field(default_factory=list)
    broader: List[Relation] = field(default_factory=list)
    narrower: List[Relation] = field(default_factory=list)
    related: List[Relation] = field(default_factory=list)

@dataclass
class ConceptRelationResult:
    """Represents a concept and its direct hierarchical relationships."""
    uri: str
    prefLabel: str
    broader: List[ConceptInfo] = field(default_factory=list)
    narrower: List[ConceptInfo] = field(default_factory=list)
    related: List[ConceptInfo] = field(default_factory=list)

@dataclass
class TopConceptsResult:
    """Represents the top concepts in the vocabulary."""
    concepts: List[TopConceptInfo] = field(default_factory=list)

# --- Helper Function for API Requests ---
async def _agrovoc_get(ctx: Context, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """A helper function to perform GET requests to the AGROVOC API."""
    url = f"{BASE_URL}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            if not resp.content:
                return {}
            return resp.json()
    except httpx.RequestError as e:
        await ctx.error(f"Network error accessing AGROVOC API at {url}: {e}")
        raise IOError("Could not connect to the AGROVOC API.")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ConceptNotFoundError(f"Concept not found for request to {url}")
        await ctx.error(f"API Error for {url}: {e.response.status_code} - {e.response.text}")
        raise ValueError(f"Invalid request to AGROVOC API: {e.response.status_code}")

# --- Tools ---

@mcp.tool
async def search_agrovoc(
    ctx: Context,
    query: Annotated[str, Field(description='The search term. Use "*" as a wildcard.')],
    lang: Annotated[str, Field(description="Language for labels (e.g., 'en', 'es', 'fr').")] = "en",
    max_hits: Annotated[int, Field(description="Maximum number of results.")] = 10
) -> SearchResults:
    """Searches for concepts within the AGROVOC vocabulary."""
    endpoint = f"/{AGROVOC_ID}/search"
    params = {"query": query, "lang": lang, "maxhits": max_hits}
    await ctx.report_progress(progress=50, message=f"Searching AGROVOC for '{query}'...")
    data = await _agrovoc_get(ctx, endpoint, params=params)
    results = [ConceptResultItem(**item) for item in data.get("results", [])]
    await ctx.report_progress(progress=100, message=f"Found {len(results)} results.")
    return SearchResults(query=query, item_count=len(results), items=results)

@mcp.tool
async def get_concept_details(
    ctx: Context,
    uri: Annotated[str, Field(description="The full URI of the AGROVOC concept (e.g., 'http://aims.fao.org/aos/agrovoc/c_3077').")],
    lang: Annotated[str, Field(description="Optional language to filter labels (e.g., 'en').")] = None
) -> Optional[ConceptDetails]:
    """
    Retrieves and parses the full details for a single concept URI from AGROVOC.
    """
    endpoint = f"/{AGROVOC_ID}/data"
    params = {"uri": uri, "format": "application/json"}
    await ctx.info(f"Fetching full details for URI: {uri}")
    try:
        data = await _agrovoc_get(ctx, endpoint, params=params)

        concept_data = next((item for item in data.get("graph", []) if item.get("uri") == uri), None)

        if not concept_data:
            raise ConceptNotFoundError(f"Concept with URI {uri} not found in the response graph.")

        def parse_labels(labels):
            if not labels: return []
            return [Label(lang=lbl.get('lang', ''), value=lbl.get('value', '')) for lbl in labels if isinstance(lbl, dict)]

        def parse_relations(relations):
            if not relations: return []
            if isinstance(relations, dict):
                return [Relation(uri=relations.get("uri"))]
            if isinstance(relations, list):
                return [Relation(uri=rel.get("uri")) for rel in relations if isinstance(rel, dict)]
            return []

        prefLabels = parse_labels(concept_data.get("prefLabel"))
        altLabels = parse_labels(concept_data.get("altLabel"))
        if lang:
            prefLabels = [lbl for lbl in prefLabels if lbl.lang == lang]
            altLabels = [lbl for lbl in altLabels if lbl.lang == lang]

        return ConceptDetails(
            uri=concept_data.get("uri", ""),
            type=concept_data.get("type", ""),
            prefLabels=prefLabels,
            altLabels=altLabels,
            broader=parse_relations(concept_data.get("broader")),
            narrower=parse_relations(concept_data.get("narrower")),
            related=parse_relations(concept_data.get("related"))
        )

    except ConceptNotFoundError as e:
        await ctx.warning(str(e))
        return None

@mcp.tool
async def get_narrower_concepts(
    ctx: Context,
    uri: Annotated[str, Field(description="URI of the concept to find narrower (more specific) concepts for.")],
    lang: Annotated[str, Field(description="The language for the labels.")] = "en"
) -> ConceptRelationResult:
    """Finds the direct narrower concepts (children) for a given AGROVOC concept URI."""
    endpoint = f"/{AGROVOC_ID}/narrower"
    params = {"uri": uri, "lang": lang}
    data = await _agrovoc_get(ctx, endpoint, params=params)
    narrower_items = [ConceptInfo(**item) for item in data.get("narrower", [])]
    return ConceptRelationResult(uri=data.get("uri", ""), prefLabel=data.get("prefLabel", ""), narrower=narrower_items)

@mcp.tool
async def get_broader_concepts(
    ctx: Context,
    uri: Annotated[str, Field(description="URI of the concept to find broader (less specific) concepts for.")],
    lang: Annotated[str, Field(description="The language for the labels.")] = "en"
) -> ConceptRelationResult:
    """Finds the direct broader concepts (parents) for a given AGROVOC concept URI."""
    endpoint = f"/{AGROVOC_ID}/broader"
    params = {"uri": uri, "lang": lang}
    data = await _agrovoc_get(ctx, endpoint, params=params)
    broader_items = [ConceptInfo(**item) for item in data.get("broader", [])]
    return ConceptRelationResult(uri=data.get("uri", ""), prefLabel=data.get("prefLabel", ""), broader=broader_items)

@mcp.tool
async def get_related_concepts(
    ctx: Context,
    uri: Annotated[str, Field(description="URI of the concept to find related concepts for.")],
    lang: Annotated[str, Field(description="The language for the labels.")] = "en"
) -> ConceptRelationResult:
    """Finds concepts that are associatively related to a given AGROVOC concept URI."""
    endpoint = f"/{AGROVOC_ID}/related"
    params = {"uri": uri, "lang": lang}
    data = await _agrovoc_get(ctx, endpoint, params=params)
    related_items = [ConceptInfo(**item) for item in data.get("related", [])]
    return ConceptRelationResult(uri=data.get("uri", ""), prefLabel=data.get("prefLabel", ""), related=related_items)

@mcp.tool
async def get_top_concepts(
    ctx: Context,
    lang: Annotated[str, Field(description="The language for the labels.")] = "en"
) -> TopConceptsResult:
    """Retrieves the top-level concepts in the AGROVOC vocabulary hierarchy."""
    endpoint = f"/{AGROVOC_ID}/topConcepts"
    params = {"lang": lang}
    data = await _agrovoc_get(ctx, endpoint, params=params)
    top_concepts = [TopConceptInfo(**item) for item in data.get("topconcepts", [])]
    return TopConceptsResult(concepts=top_concepts)


# --- Prompts ---

@mcp.prompt
def find_and_explore_agrovoc_concept() -> tuple:
    """Provides an example prompt for searching AGROVOC and exploring a concept's hierarchy."""
    return (
        Message("I can help you explore the AGROVOC vocabulary. For example, I can find a concept and then show you what concepts are more specific.", role="assistant"),
        Message(
            "First, use the `search_agrovoc` tool to search for 'potatoes'. Then, take the URI of the first result and use the `get_narrower_concepts` tool to find its children concepts.",
            role="user"
        ),
    )

# --- Server Execution ---

if __name__ == "__main__":
    mcp.run()
