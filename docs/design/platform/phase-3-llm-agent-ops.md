# Phase 3 – LLM & Agent Ops Blueprint

## 1. Goals
- Triển khai nền tảng LLMOps/AgentOps để hỗ trợ customer support, observability automation, marketing automation, triage incident.
- Kết nối với stack DataOps/MLOps (Phase 1-2) để đảm bảo data quality, feature availability, model governance.
- Chuẩn hóa vòng đời agent: dữ liệu → embedding/vector store → prompt/context → evaluation → deployment → monitoring.

## 2. Component Overview
| Component | Role | Image/Version | Dependencies |
| --- | --- | --- | --- |
| Qdrant (Vector DB) | Lưu embedding cho RAG | `qdrant/qdrant:1.8` | MinIO (backup), Kafka (optional events) |
| vLLM / Open-source LLM Server | Low-latency inference for LLMs (Llama, Mistral) | `vllm/vllm-openai:latest` | GPU optional, config for CPU fallback |
| LangChain Orchestrator | Agent runtime (tooling, planning) | Custom FastAPI service | Qdrant, LLM server |
| RAG Ingestion Pipeline | Airflow DAG ingest docs → embedding | Airflow, Ray, Feast features |
| Trulens/Evidently Agent Monitor | Evaluate agent quality, track hallucination | `arizeai/trulens` (or custom) | Prometheus, MLflow |
| Knowledge Base | Structured docs (DataHub, runbooks) | DataHub API, MinIO |
| Observability Hooks | Tools for agent to query Grafana, Prometheus, Trino | API tokens, RBAC |

## 3. Architecture Snapshot
```text
      ┌─────────────────────┐         ┌────────────────┐
      │   DataHub / Docs    │         │  Iceberg Tables│
      └────────┬────────────┘         └───────┬────────┘
               │ ingest Airflow DAG            │
               ▼                               ▼
        ┌──────────────┐         ┌─────────────────────┐
        │  RAG Builder │────────►│  Qdrant Vector Store│
        └──────────────┘   upsert│  Collections: support,│
                                 │  ops, marketing      │
                                 └────────┬─────────────┘
                                          │
                               ┌──────────▼───────────────┐
                               │ LangChain Agent Service  │
                               │ - Tools: Grafana API,    │
                               │   Trino query, Jira, etc │
                               └──────────┬───────────────┘
                                          │calls
                          ┌───────────────▼────────────┐
                          │ vLLM Server / OpenAI Proxy │
                          └───────────────┬────────────┘
                                          │outputs
                                   ┌──────▼─────────┐
                                   │ Monitoring     │
                                   │ (Prom, Grafana │
                                   │  Trulens)      │
                                   └────────────────┘
```

## 4. Deployment Plan
### 4.1 Qdrant Vector Database
```yaml
  qdrant:
    image: qdrant/qdrant:1.8.3
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      QDRANT__SERVICE__GRPC_PORT: 6334
    networks: [datanet]
```
- Collections schema: `support_kb`, `ops_runbooks`, `marketing_templates`, `product_catalog_embeddings`.
- Backup strategy: nightly snapshot to MinIO via Airflow DAG.

### 4.2 LLM Serving (vLLM)
```yaml
  vllm:
    image: vllm/vllm-openai:latest
    command: ["--model", "mistralai/Mistral-7B-Instruct", "--host", "0.0.0.0"]
    environment:
      VLLM_ATTENTION_BACKEND: xformers
      HF_TOKEN: ${HF_TOKEN}
    ports:
      - "8001:8000"
    volumes:
      - ./models:/models  # optional local cache
    networks: [datanet]
```
- Provide fallback to external API (OpenAI/Azure) if GPU not available; configure within LangChain service.
- Security: front with API gateway (Traefik) or token-based auth.

### 4.3 LangChain Agent Service
- Custom FastAPI app `agent-service` containing:
  - Tools: Prometheus query, Grafana snapshot, Trino SQL, Jira ticket creation, Support-service API, Notification-service API.
  - Memory: store conversation state in Redis (existing), embedding retrieval from Qdrant.
  - Router to choose agent persona (support, ops, marketing).
- Compose entry:
```yaml
  agent-service:
    build: ./services/agent-service
    environment:
      QDRANT_URL: http://qdrant:6333
      LLM_ENDPOINT: http://vllm:8000/v1
      PROMETHEUS_URL: http://prometheus:9090
      GRAFANA_API: http://grafana:3000
    ports:
      - "8085:8080"
    depends_on: [qdrant, vllm, prometheus, grafana]
    networks: [datanet]
```
- Use LangChain Expression Language (LCEL) to define agent chains.
- Incorporate tool auth via API keys (store in Vault/secrets).

### 4.4 RAG Ingestion Pipeline
- Airflow DAG `rag_ingestion.py` steps:
  1. Extract docs from DataHub (metadata descriptions), Confluence/Jira via API, Markdown in repo (`docs/`), dashboards snapshots from Grafana.
  2. Preprocess with Ray (parallel text chunking) or Python operator; run embedding using Hugging Face model (sentence-transformers) deployed via Ray Serve.
  3. Upsert into Qdrant collections.
  4. Log ingestion metrics to Prometheus (`rag_ingest_documents_total`).

### 4.5 Agent Evaluation & Monitoring
- Integrate Trulens or custom evaluator pipeline:
  - Capture dialogs (inputs, tool calls, outputs) -> store in MinIO and MLflow for reproducibility.
  - Automatic metrics: hallucination via reference retrieval, answer relevancy, toxicity.
  - Use Evidently for data drift on agent usage metrics.
- Grafana dashboards: `agent_latency_seconds`, `agent_success_rate`, `rag_hit_rate`.
- Alertmanager rules for failure spikes, hallucination > threshold.

### 4.6 Security & Compliance
- RBAC: restrict tool usage per persona (support agent cannot modify infrastructure without approval).
- Audit: log all agent actions via Loki with structured trace (`agent_id`, `tool`, `resource`).
- Consent: ensure customer data usage respects GDPR; integrate with customer preferences from `customer-service`.

## 5. Use Case Alignment
| Use Case | AgentOps Solution |
| --- | --- |
| Customer Support 360 | Support agent queries Qdrant + calls order/payment/fulfillment APIs; generates personalized responses, suggests actions; logs resolution to support-service. |
| Observability Triage | Ops agent monitors Prometheus alerts, queries Grafana, correlates with in-flight incidents, proposes remediation steps. |
| Marketing Personalization | Agent collaborates with recommendation/pricing signals; crafts email/SMS copy tailored to segment; integrates with notification-service for distribution. |
| Fraud Investigation | Agent accesses MLflow experiment history, Ray metrics, reconstructs decisions, flags anomalies. |
| Incident Runbook | Agents read `docs/monitoring/incident-runbook.md`, propose runbook improvements, highlight missing metrics. |

## 6. Integration with Previous Phases
- Airflow orchestrates RAG ingestion, pulling features/metadata from Feast/MLflow/DataHub.
- Feast features (e.g., customer segment) supplied to agents for contextual responses.
- MLflow records agent model versions (prompt templates) for governance.
- DataHub registers agent datasets, vector collections, tool catalogs.

## 7. Backlog & Ownership
| ID | Task | Owner | Priority |
| --- | --- | --- | --- |
| AGENT-01 | Deploy Qdrant service + backup workflow | Platform | High |
| AGENT-02 | Deploy vLLM container (with fallback configuration) | Platform | High |
| AGENT-03 | Implement agent-service (LangChain) with core tools | AI Eng | High |
| AGENT-04 | Build Airflow DAG for RAG ingestion | Data Eng | High |
| AGENT-05 | Integrate Trulens/Evidently for agent evaluation | AI Ops | Medium |
| AGENT-06 | Add Grafana dashboard + Alertmanager rules for agent metrics | Observability | Medium |
| AGENT-07 | Define security policies, secrets management for tool auth | Security | Medium |
| AGENT-08 | Document agent governance & runbooks | AI Ops | Medium |

## 8. Risks & Mitigations
- **Hallucinations**: enforce strict grounding via top-k retrieval, apply output guardrails (prompt, classifier). Run human-in-loop for critical actions.
- **Cost/Resource**: evaluate CPU vs GPU LLM; scale down containers off-peak; consider quantized models.
- **Security**: limit tool permissions, set approvals for high-risk operations, log actions.
- **Data privacy**: respect customer consent, mask PII in embeddings, set vector retention policies.

## 9. Next Steps
1. Prepare docker-compose extension adding Qdrant, vLLM, agent-service, vector volumes.
2. Scaffold `services/agent-service/` with LangChain FastAPI skeleton and tool adapters.
3. Author Airflow DAG + scripts for RAG ingestion (Phase 3 tasks). 
4. Define evaluation scripts leveraging Trulens and integrate with CI for regression checks.
5. Align with support/marketing teams on agent personas and approval workflows.
