"""Read-only assistant contracts using synthetic cases and a fake Responses client."""

import asyncio
import copy
import json
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

PROJECT = Path(__file__).resolve().parents[1] / "money_graph"
sys.path.insert(0, str(PROJECT))

from mg.assistant import AssistantUnavailable, GraphTools, ask_openai, settings, validate_answer


A, B, C, D, E, F, G, H = [str(100000000000000001 + offset) for offset in range(8)]
UNKNOWN = "999999999999999999"


@pytest.fixture(autouse=True)
def no_real_openai_credentials(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


@pytest.fixture
def case_files(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    out.mkdir()
    links = [
        (A, C, 100), (B, C, 200), (G, C, 50),
        (A, E, 90), (B, E, 210),
        (A, F, 500), (B, F, 600),
        (C, D, 40), (E, D, 50), (D, H, 30),
    ]
    pd.DataFrame([
        {"src": int(src), "dst": int(dst), "sum_kzt": float(amount), "n_tx": 1, "depth": 1}
        for src, dst, amount in links
    ]).to_parquet(data / "edges.parquet")
    pd.DataFrame([
        {
            "gid": gid, "role": "distributor" if gid in (A, B) else "peripheral",
            "evidence": f"Наблюдаемые переводы счёта {gid}.",
            "priority_score": 0.5, "priority_role": 0.2, "priority_turnover": 0.3,
            "in_kzt": sum(amount for _, dst, amount in links if dst == gid),
            "out_kzt": sum(amount for src, _, amount in links if src == gid),
            "depth": 0 if gid in (A, B, G) else 1, "is_seed": gid in (A, B, G),
        }
        for gid in (A, B, C, D, E, F, G, H)
    ]).to_csv(out / "nodes_roles.csv", index=False)
    pd.DataFrame([
        {"gid": C, "request_type": "incoming_external", "weight": 350.0,
         "reason": "Запросить внешние поступления."},
        {"gid": H, "request_type": "next_hop_outgoing", "weight": 30.0,
         "reason": "Запросить следующий хоп."},
    ]).to_csv(out / "requests.csv", index=False)
    (out / "summary.json").write_text(json.dumps({
        "period_start": "2026-07-01", "period_end": "2026-07-31",
        "min_tx_kzt": 1, "max_depth": 4,
    }), encoding="utf-8")
    return data, out


@pytest.fixture
def graph(case_files):
    return GraphTools(*case_files)


def answer_payload(gids=(), edges=(), answer="Объяснение по полученным данным."):
    return {"answer": answer, "evidence_gids": list(gids), "edge_ids": list(edges)}


def test_details_preserve_large_identifiers_and_use_computed_facts(graph):
    result = graph.preset("explain", [A, A])
    assert result["mode"] == "local"
    assert result["tools_used"] == ["get_node_details"]
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["gid"] == A
    assert node["out_kzt"] == 690
    assert node["priority_score"] == 0.5
    assert sorted(node["priority_contributions"].values()) == [0.2, 0.3]
    assert [(edge["src"], edge["dst"]) for edge in node["largest_links"]] == [(A, F), (A, C), (A, E)]
    assert all(isinstance(edge["src"], str) and isinstance(edge["dst"], str) for edge in result["edges"])
    assert A in result["answer"]
    assert result["limitations"]
    assert graph.seen_nodes.keys() == {A, C, E, F}


def test_details_use_extended_role_when_strict_export_says_peripheral(case_files):
    data, out = case_files
    path = out / "nodes_roles.csv"
    nodes = pd.read_csv(path, dtype={"gid": str})
    nodes["role_detail"] = ""
    nodes.loc[nodes.gid == C, "role_detail"] = "truncated"
    nodes.to_csv(path, index=False)
    summary_path = out / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["max_depth"] = 2
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    graph = GraphTools(data, out)
    details = graph.get_node_details([C])
    assert details["nodes"][0]["role"] == "truncated"
    assert details["evidence"][0]["reason"].startswith("Обрезан на 2-м хопе:")
    assert graph.get_node_details([A])["nodes"][0]["role"] == "distributor"


@pytest.mark.parametrize("gids", [[], [A] * 6, [int(A)], [UNKNOWN], A])
def test_gid_validation_rejects_invalid_selections(graph, gids):
    with pytest.raises(ValueError):
        graph.get_node_details(gids)


def test_common_recipients_rank_by_payer_count_then_amount(graph):
    result = graph.preset("common_recipients", [A, B, G])
    assert [item["gid"] for item in result["recipients"]] == [C, F, E]
    assert result["total_recipients"] == 3
    assert result["recipients"][0] == {"gid": C, "payer_gids": [A, B, G], "sum_kzt": 350.0}
    assert result["recipients"][1]["payer_gids"] == [A, B]
    assert "от 2 из 3" in result["answer"]
    assert len(result["edges"]) == 7


def test_common_recipients_empty_and_single_payer_cases(graph):
    assert graph.find_common_recipients([A, H])["recipients"] == []
    with pytest.raises(ValueError):
        graph.find_common_recipients([A, A])


def test_paths_are_shortest_directed_bounded_and_deterministic(graph):
    result = graph.find_paths(A, H, max_hops=3)
    assert result["path"] == [A, C, D, H]
    assert [(edge["src"], edge["dst"]) for edge in result["edges"]] == [(A, C), (C, D), (D, H)]
    assert graph.find_paths(A, H, max_hops=2)["path"] == []
    assert graph.find_paths(H, A)["path"] == []
    assert graph.preset("paths", [A, D])["path"] == [A, C, D]


@pytest.mark.parametrize("max_hops", [0, 5, True, "4"])
def test_paths_reject_invalid_depth(graph, max_hops):
    with pytest.raises(ValueError):
        graph.find_paths(A, H, max_hops)


def test_paths_require_two_distinct_accounts(graph):
    with pytest.raises(ValueError):
        graph.find_paths(A, A)
    with pytest.raises(ValueError):
        graph.preset("paths", [A, B, C])


def test_missing_requests_are_filtered_and_keep_exact_ids(graph):
    result = graph.preset("missing_data", [C])
    assert result["requests"] == [{
        "gid": C, "request_type": "incoming_external", "weight": 350.0,
        "reason": "Запросить внешние поступления.",
    }]
    assert [item["gid"] for item in result["evidence"]] == [C]
    empty = graph.get_missing_data_requests([A])
    assert empty["requests"] == []
    assert "не означает полноту" in empty["answer"]


def test_tool_dispatch_rejects_unknown_tools_and_unexpected_arguments(graph):
    with pytest.raises(ValueError):
        graph.call("execute_code", {"code": "anything"})
    with pytest.raises(ValueError):
        graph.call("get_node_details", {"gids": [A], "unexpected": True})


def test_valid_answer_reuses_only_seen_evidence_and_deduplicates(graph):
    graph.preset("explain", [A])
    result = validate_answer(answer_payload([A, C, A], [f"{A}>{C}", f"{A}>{C}"]), graph)
    assert result["mode"] == "openai"
    assert [item["gid"] for item in result["evidence"]] == [A, C]
    assert result["edges"] == [graph.edges[(A, C)]]
    assert result["tools_used"] == ["get_node_details"]


@pytest.mark.parametrize("gids,edges", [
    ([UNKNOWN], []), ([H], []), ([int(A)], []),
    ([], [f"{A}>{UNKNOWN}"]), ([], [f"{D}>{H}"]),
])
def test_answers_reject_nonexistent_and_existing_but_unseen_references(graph, gids, edges):
    graph.get_node_details([A])
    assert H in graph.nodes and H not in graph.seen_nodes
    assert (D, H) in graph.edges and (D, H) not in graph.seen_edges
    with pytest.raises(AssistantUnavailable):
        validate_answer(answer_payload(gids, edges), graph)


@pytest.mark.parametrize("payload", [
    {}, {**answer_payload(), "unexpected": True}, answer_payload(answer=" "),
    answer_payload(answer="x" * 6001), answer_payload([A] * 31),
    answer_payload(edges=[f"{A}>{C}"] * 51),
])
def test_answers_reject_invalid_format_or_limits(graph, payload):
    graph.get_node_details([A])
    with pytest.raises(AssistantUnavailable):
        validate_answer(payload, graph)


class FakeFunctionCall:
    type = "function_call"

    def __init__(self, name="get_node_details", args=None, call_id="call_1"):
        self.name = name
        self.arguments = json.dumps({"gids": [A]} if args is None else args)
        self.call_id = call_id

    def model_dump(self, exclude_none=True):
        return {"type": self.type, "name": self.name, "arguments": self.arguments, "call_id": self.call_id}


def response(output=(), payload=None, status="completed", output_text=None):
    return SimpleNamespace(
        status=status, output=list(output),
        output_text=json.dumps(payload) if output_text is None else output_text,
    )


class FakeResponses:
    def __init__(self, responses):
        self.pending = deque(responses)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        assert self.pending, "Assistant exceeded the scripted number of API calls"
        return self.pending.popleft()


def client_for(*responses):
    return SimpleNamespace(responses=FakeResponses(responses))


def test_fake_responses_roundtrip_returns_verified_tool_references(graph):
    client = client_for(
        response([FakeFunctionCall()]),
        response(payload=answer_payload([A, C], [f"{A}>{C}"])),
    )
    result = asyncio.run(ask_openai(graph, [A], "Почему этот счёт в списке?", client=client))
    assert result["mode"] == "openai"
    assert result["evidence"][0]["gid"] == A
    assert result["edges"][0]["dst"] == C
    first, second = client.responses.requests
    assert first["tool_choice"] == "required"
    assert first["store"] is False
    assert first["parallel_tool_calls"] is False
    assert first["text"]["format"]["strict"] is True
    assert json.loads(first["input"][0]["content"])["selected_gids"] == [A]
    tool_output = second["input"][-1]
    assert tool_output["type"] == "function_call_output"
    assert tool_output["call_id"] == "call_1"
    assert json.loads(tool_output["output"])["nodes"][0]["gid"] == A
    assert not client.responses.pending


def test_invalid_tool_arguments_return_an_error_to_model(graph):
    call = FakeFunctionCall(args={"gids": [UNKNOWN]})
    client = client_for(response([call]), response(payload=answer_payload(answer="Счёт не найден.")))
    result = asyncio.run(ask_openai(graph, [A], "Покажи счёт", client=client))
    output = json.loads(client.responses.requests[1]["input"][-1]["output"])
    assert "error" in output
    assert result["evidence"] == []
    assert graph.seen_nodes == {}


def test_model_roundtrip_rejects_citations_not_returned_by_tool(graph):
    client = client_for(
        response([FakeFunctionCall()]),
        response(payload=answer_payload([H], [f"{D}>{H}"])),
    )
    with pytest.raises(AssistantUnavailable, match="непроверенные"):
        asyncio.run(ask_openai(graph, [A], "Объясни", client=client))


def test_responses_refusal_and_incomplete_output_fail_safely(graph):
    for refused in (
        response(output=[SimpleNamespace(type="message", content=[{"type": "refusal", "refusal": "No"}])], output_text=""),
        response(status="incomplete", output_text=""),
        response(output_text="not json"),
    ):
        with pytest.raises(AssistantUnavailable):
            asyncio.run(ask_openai(graph, [A], "Объясни", client=client_for(refused)))


def test_assistant_stops_after_four_model_requests(graph):
    client = client_for(*(response([FakeFunctionCall(call_id=f"call_{n}")]) for n in range(4)))
    with pytest.raises(AssistantUnavailable, match="лимит"):
        asyncio.run(ask_openai(graph, [A], "Продолжай", client=client))
    assert len(client.responses.requests) == 4
    assert client.responses.requests[-1]["tool_choice"] == "none"
    assert len(graph.tools_used) == 3


def test_assistant_enforces_six_tool_call_limit(graph):
    client = client_for(
        response([FakeFunctionCall(call_id=f"call_{n}") for n in range(6)]),
        response([FakeFunctionCall(call_id="call_7")]),
    )
    with pytest.raises(AssistantUnavailable, match="лимит"):
        asyncio.run(ask_openai(graph, [A], "Продолжай", client=client))
    assert len(graph.tools_used) == 6
    assert client.responses.requests[-1]["tool_choice"] == "none"


def test_missing_key_disables_ai_without_disabling_local_actions(graph):
    assert settings() == {"configured": False, "model": None}
    assert graph.preset("explain", [A])["mode"] == "local"
    with pytest.raises(AssistantUnavailable, match="не подключены"):
        asyncio.run(ask_openai(graph, [A], "Объясни"))


def test_blank_question_is_rejected_before_calling_client(graph):
    client = client_for()
    with pytest.raises(ValueError):
        asyncio.run(ask_openai(graph, [A], "  ", client=client))
    assert client.responses.requests == []
