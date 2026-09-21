"""Chat graph: restate a follow-up, split a multi-part question, retrieve corpus context,
run the assess ⇄ assess_tools loop, then synthesize a cited answer — or refuse, before any
model call, a question the corpus does not cover."""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.chat.enums import ChatNode
from app.chat.graph.nodes.assess import assess, assess_tools
from app.chat.graph.nodes.decompose import decompose
from app.chat.graph.nodes.refuse import refuse
from app.chat.graph.nodes.retrieve import retrieve
from app.chat.graph.nodes.rewrite import rewrite
from app.chat.graph.nodes.synthesize import synthesize
from app.chat.models import ChatState
from app.core.config import config


def assess_tools_or_synthesize(state: ChatState) -> ChatNode:
    """After assess: run what it asked for, or answer when it asked for nothing."""
    return ChatNode.SYNTHESIZE if state.context_settled else ChatNode.ASSESS_TOOLS


def assess_or_synthesize_or_refuse(state: ChatState) -> ChatNode:
    """After retrieve or a tool round: refuse for want of context — none cleared the gate,
    or assess found what there is bears on nothing — else review again while budget
    remains, or answer with what there is."""
    if not state.sources or state.refusal is not None:
        return ChatNode.REFUSE
    return ChatNode.SYNTHESIZE if state.context_settled else ChatNode.ASSESS


def decompose_or_retrieve(state: ChatState) -> ChatNode:
    """At the start: split the question when the node is on, else search it as asked. An
    edge rather than a check inside the node, so a run with it off records no step."""
    return ChatNode.DECOMPOSE if config.DECOMPOSE_ENABLED else ChatNode.RETRIEVE


def rewrite_or_decompose_or_retrieve(state: ChatState) -> ChatNode:
    """At the start: restate a follow-up first, since the thread is what its pronouns
    mean; a first question takes the edge decompose_or_retrieve would."""
    return ChatNode.REWRITE if state.history else decompose_or_retrieve(state)


def build_graph() -> CompiledStateGraph[ChatState]:
    """The compiled (rewrite →) (decompose →) retrieve → (assess ⇄ assess_tools) →
    (synthesize | refuse) graph."""
    graph = StateGraph(ChatState)
    graph.add_node(ChatNode.REWRITE, rewrite)
    graph.add_node(ChatNode.DECOMPOSE, decompose)
    graph.add_node(ChatNode.RETRIEVE, retrieve)
    graph.add_node(ChatNode.ASSESS, assess)
    graph.add_node(ChatNode.ASSESS_TOOLS, assess_tools)
    graph.add_node(ChatNode.SYNTHESIZE, synthesize)
    graph.add_node(ChatNode.REFUSE, refuse)
    graph.add_conditional_edges(
        START,
        rewrite_or_decompose_or_retrieve,
        [ChatNode.REWRITE, ChatNode.DECOMPOSE, ChatNode.RETRIEVE],
    )
    graph.add_conditional_edges(
        ChatNode.REWRITE, decompose_or_retrieve, [ChatNode.DECOMPOSE, ChatNode.RETRIEVE]
    )
    graph.add_edge(ChatNode.DECOMPOSE, ChatNode.RETRIEVE)
    graph.add_conditional_edges(
        ChatNode.RETRIEVE,
        assess_or_synthesize_or_refuse,
        [ChatNode.ASSESS, ChatNode.SYNTHESIZE, ChatNode.REFUSE],
    )
    graph.add_conditional_edges(
        ChatNode.ASSESS, assess_tools_or_synthesize, [ChatNode.ASSESS_TOOLS, ChatNode.SYNTHESIZE]
    )
    graph.add_conditional_edges(
        ChatNode.ASSESS_TOOLS,
        assess_or_synthesize_or_refuse,
        [ChatNode.ASSESS, ChatNode.SYNTHESIZE, ChatNode.REFUSE],
    )
    graph.add_edge(ChatNode.SYNTHESIZE, END)
    graph.add_edge(ChatNode.REFUSE, END)
    return graph.compile()


chat_graph = build_graph()
