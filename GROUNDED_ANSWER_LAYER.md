# ExoTrace: Evidence-Grounded Answer Layer

This patch adds an answer-generation layer over the existing ExoTrace retriever. It does not add a new scientific glossary, canned answers, question-specific routes, or a default model ID.

## What it does

1. Calls the existing `HybridTextRetriever.search` with the explicitly selected `strategy` and `scope`.
2. Assigns answer-local IDs (`E1`, `E2`, ...) to the actual retrieved documents and retains source URLs, catalogue-record IDs, snapshot IDs, and source files where available.
3. Calls the OpenAI Responses API with the current evidence and a strict JSON Schema response format.
4. Requires each factual claim to cite one or more evidence IDs from the current retrieval result set.
5. Rejects unknown/fabricated evidence IDs, missing citations, malformed outputs, and claim-bearing abstentions.
6. Renders citations from stored provenance rather than allowing the model to invent URLs.
7. Abstains without making an API call if retrieval returned no usable evidence.
8. Optionally saves the generated answer and supporting evidence to JSON.

The code validates citation structure, not semantic entailment. A citation ID being valid does not prove that the source logically supports every word of a claim. This is stated in the module documentation and should remain a limitation in any project demo.

## Configure your model locally

The model identifier is deliberately not hardcoded. Add these entries to your existing `.env` file without removing your Neo4j settings:

```dotenv
OPENAI_API_KEY=put_your_key_here
EXOTRACE_LLM_MODEL=put_a_model_id_available_to_your_API_account_here
```

Never commit `.env` or paste API keys into chat. Process environment variables override values in `.env`. Optional settings:

```dotenv
EXOTRACE_OPENAI_RESPONSES_URL=https://api.openai.com/v1/responses
EXOTRACE_LLM_TIMEOUT_SECONDS=60
EXOTRACE_LLM_MAX_OUTPUT_TOKENS=1400
```

The implementation uses Python's standard library for HTTP; no OpenAI SDK dependency is required.

## Run it

From the ExoTrace workspace, after the existing vector dependencies and corpus/index have been installed and built:

```powershell
python -m exotrace.answering.ask --query "What does planetary orbital eccentricity describe?"
```

Select retrieval explicitly when needed:

```powershell
python -m exotrace.answering.ask --query "What does planetary orbital eccentricity describe?" --strategy dense --scope references --top-k 6
```

The default strategy is the existing measured dense baseline, and the default scope is `references` (NASA explanatory chunks plus source-derived parameter definitions). `--scope profiles` and `--scope all` are available, but generated planet profiles are search aids, not independent scientific sources. Exact numerical answers should be supported by the original catalogue record/Neo4j path rather than a profile alone; a future graph-tool integration should retrieve those records directly.

To save the full provenance payload:

```powershell
python -m exotrace.answering.ask --query "What does planetary orbital eccentricity describe?" --save-json data/manifests/last_answer.json
```

## Test coverage

The new tests cover evidence metadata, context limits, claim citation requirements, unknown evidence ID rejection, abstention, structured API request construction, and environment configuration without making network/API calls.
