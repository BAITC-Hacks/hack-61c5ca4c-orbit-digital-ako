# Deployment handoff and external service contract

[Русский](../../README.md) · [English](../../README.en.md) · [Қазақша](../../README.kk.md)

This document describes the current implementation in `api/assistant.py` and `mg/assistant.py`. It gives a deployment operator the required settings, network access and request/response boundaries. Runtime credentials are deliberately absent.

## What the operator receives

The repository contains the application source, the frontend npm lockfile, Docker build/Compose files, bundled demonstration data and `.env.example`. Start from the repository root with:

```sh
docker compose up --build -d
```

No database server, message broker, object-storage account or OpenAI key is required for local analysis. Completed investigations are stored under `/data/projects` in the `moneygraph_data` Compose volume. The application is a single-analyst local MVP with no authentication; the default published address is `127.0.0.1:8000`.

For enabled AI questions, the operator must separately supply:

- `OPENAI_API_KEY`: a valid API-project credential, supplied privately at runtime.
- `OPENAI_MODEL`: optional, defaults to `gpt-4.1-mini`; the API project must have access to a compatible model.
- Outbound DNS resolution and HTTPS access to `api.openai.com:443`.
- An API project with available quota/billing. A browser ChatGPT subscription is not substituted for this credential.

Compose reads the optional **local** `money_graph/.env` when it creates the container. A deployment service can inject environment variables directly when it starts the image instead. The Docker build does not need the key. Do not use a build argument or a frontend `VITE_*` variable to supply it.

Changing a local runtime file requires container recreation:

```sh
docker compose up -d --force-recreate app
```

`docker compose restart` alone does not reload Compose's environment. Avoid sharing expanded Compose configurations or complete container inspection output: these can contain runtime secrets.

## Network boundaries

At build time, Docker downloads its Node and Python base images and package managers download npm/Python dependencies. The runtime serves fonts, chart/graph libraries and Swagger resources locally.

The browser talks to the same-origin FastAPI backend. It does not receive the API key and does not call OpenAI directly. Only an explicitly confirmed assistant question invokes the provider. `/api/health` reports `offline: true` for the local analysis design; this is **not** a statement that a separately enabled OpenAI question will stay offline.

## Application API

The live schema is available at `/api/openapi.json`; the local interactive reference is `/api/docs`.

### Assistant availability

```http
GET /api/assistant/status
```

Configured response:

```json
{
  "configured": true,
  "model": "gpt-4.1-mini",
  "local_tools": true,
  "external_default": false
}
```

Without a key or the optional SDK, `configured` is `false` and `model` is `null`. This endpoint checks local settings, not provider authentication, quota or connectivity.

### Local explanation

Create/import a project and complete analysis first. Replace the example project and account identifiers with existing values; identifiers are JSON strings.

```http
POST /api/projects/{project_id}/assistant
Content-Type: application/json
```

```json
{
  "gids": ["account-001"],
  "mode": "explain"
}
```

Local modes are `explain`, `common_recipients`, `paths` and `missing_data`. There must be one to five selected accounts. Common recipients requires at least two; a path requires exactly two in source-to-destination order. Local actions do not invoke the provider.

### Model question

The same endpoint accepts:

```json
{
  "gids": ["account-001", "account-002"],
  "mode": "question",
  "question": "Explain why these accounts deserve review and cite the available evidence.",
  "allow_external": true
}
```

`question` is limited to 1,000 characters and must be nonblank for model questions. `allow_external` defaults to `false`; each question needs explicit confirmation. Unknown request fields are rejected. A request from a different browser origin is rejected by the application's origin checks.

Illustrative successful application response:

```json
{
  "answer": "The observed links support further review; the available data does not establish intent.",
  "evidence": [{"gid": "account-001", "reason": "Evidence from the current calculation."}],
  "edges": [{"src": "account-001", "dst": "account-002", "sum_kzt": 12500.0, "n_tx": 2}],
  "limitations": ["Roles are hypotheses, not findings of guilt."],
  "mode": "openai",
  "tools_used": ["get_node_details"],
  "notice": "An AI explanation based on computed results. Verify it against the referenced links."
}
```

Text and evidence above are synthetic examples, not stored project data. Local responses use `mode: "local"`, can include additional tool-specific facts, and have `notice: null`. The legacy `sum_kzt` field name is retained by the assistant adapter; interpret the value using the project's configured currency, not the name of that field.

## OpenAI provider request and response

The Python SDK sends JSON over HTTPS:

```http
POST https://api.openai.com/v1/responses
Authorization: Bearer <runtime OPENAI_API_KEY>
Content-Type: application/json
```

The application supplies `model`, instructions, the question and selected account IDs, collection parameters, tool definitions, and a strict JSON output schema. Requests set `parallel_tool_calls: false`, `store: false` and `max_output_tokens: 2000`. Refer to the source for the complete dynamically constructed payload.

Four server-side, read-only tools are exposed:

1. `get_node_details`: computed metrics and relevant links for selected accounts.
2. `find_common_recipients`: recipients shared by at least two selected payers.
3. `find_paths`: a bounded directed structural path.
4. `get_missing_data_requests`: follow-up data requests from the analysis.

A provider response can request a tool using a `function_call` output item with `name`, JSON `arguments` and `call_id`. The backend executes the allowed function and sends a matching `function_call_output` in the next Responses request. This is the Responses API [function-calling flow](https://developers.openai.com/api/docs/guides/function-calling).

The final provider text is required to encode this object:

```json
{
  "answer": "An explanation based on the tool results.",
  "evidence_gids": ["account-001"],
  "edge_ids": ["account-001>account-002"]
}
```

The backend parses this JSON, checks cited IDs against tool results from the current question, and produces the application response above. A valid JSON schema does not prove the factual accuracy of every sentence. See the official [structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

The app sends selected context and bounded tool results, not an upload of every source file. Selected results may still contain sensitive transaction information. `store: false` is not a blanket guarantee of no provider retention; consult the applicable [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

## Limits and failures

- At most four provider requests and six tool calls per user question.
- At most 2,000 output tokens per provider request.
- SDK timeout: 20 seconds per request; automatic SDK retries are disabled.
- Overall model-answer timeout: 60 seconds; one concurrent model question per process.
- The UI cancelling a request does not guarantee that an already submitted provider request avoids charges.

Errors use the application HTTP response, normally `{"detail": "A safe user-facing message"}`. Schema validation can return a `detail` array of field errors.

- `409`: the project has no completed analysis.
- `422`: invalid selection/question, absent external-transfer confirmation, or request validation failure.
- `429`: another question is running, or the provider reports a rate/quota limit.
- `503`: missing configuration, provider connection failure, or an answer that could not be validated/completed.
- `504`: provider or overall response timeout.
- `502`: invalid provider API key, upstream server error, or an unexpected provider failure. A provider-key error is not an application-login error.
- Provider permission, unavailable-model and invalid-parameter errors can map to `403`, `404` and `400` respectively.

Raw provider messages, authorization headers and credentials are not returned to the browser. Test integration with synthetic data. Successful health and status checks do not replace a separately authorized live provider test.
