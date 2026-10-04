"""The LangGraph state machine wiring the pipeline nodes (SPEC 3)."""

from functools import partial
from itertools import pairwise
from typing import Any

from langgraph.graph import END, START, StateGraph
from pymongo.asynchronous.collection import AsyncCollection

from app.db.client import Document
from app.pipeline import nodes
from app.pipeline.nodes import PipelineDeps, Retriever
from app.pipeline.state import PipelineState
from app.retrieval.embeddings import Embedder
from app.retrieval.search import retrieve
from app.rules.models import CompanyFacts
from app.schemas.analysis import ItemAnalysis
from app.schemas.regulation import RegulationHit
from app.schemas.resolution import ResolutionType

NODE_ORDER = ("parse", "extract", "validate", "retrieve", "rule_check", "reason", "assemble")


def build_graph(deps: PipelineDeps) -> Any:
    """Compile the graph; dependencies are bound into the nodes, so nodes see only state."""
    graph = StateGraph(PipelineState)
    graph.add_node("parse", nodes.parse)
    graph.add_node("extract", partial(nodes.extract, deps=deps))
    graph.add_node("validate", nodes.validate)
    graph.add_node("retrieve", partial(nodes.retrieve, deps=deps))
    graph.add_node("rule_check", partial(nodes.rule_check, deps=deps))
    graph.add_node("reason", partial(nodes.decide, deps=deps))
    graph.add_node("assemble", nodes.assemble)
    graph.add_edge(START, NODE_ORDER[0])
    for current, following in pairwise(NODE_ORDER):
        graph.add_edge(current, following)
    graph.add_edge(NODE_ORDER[-1], END)
    return graph.compile()


async def analyse_notice(
    deps: PipelineDeps, pdf: bytes, company: CompanyFacts | None = None
) -> list[ItemAnalysis]:
    """Run a notice PDF through the whole pipeline."""
    state = PipelineState(pdf=pdf, company=company or CompanyFacts())
    final = await build_graph(deps).ainvoke(state)
    return list(final["analyses"])


def atlas_retriever(
    collection: AsyncCollection[Document], embedder: Embedder, *, hybrid: bool = False
) -> Retriever:
    """The production retriever: Atlas vector (or hybrid) search over `regulations`."""

    async def run(
        query: str, resolution_type: ResolutionType | None, k: int
    ) -> list[RegulationHit]:
        return await retrieve(collection, embedder, query, resolution_type, k, hybrid=hybrid)

    return run
