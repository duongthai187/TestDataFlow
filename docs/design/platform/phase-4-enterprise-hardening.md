# Phase 4 – Enterprise Hardening & Governance Blueprint

## 1. Goals
- Củng cố nền tảng AI/ML/Data/Agent Ops để đáp ứng yêu cầu enterprise: bảo mật, compliance, multi-region, self-service, quan sát toàn diện.
- Đảm bảo quy trình triển khai/vận hành model/agent tuân thủ audit, có khả năng rollback, đáp ứng SLA.
- Chuẩn bị cho chuyển đổi lên Kubernetes/Cloud khi scale lớn hơn.

## 2. Pillars
1. **Security & Access Control**: secrets management, RBAC, policy enforcement, audit trail.
2. **Resilience & Scalability**: multi-region failover, backup & disaster recovery, autoscaling.
3. **Self-Service & Productivity**: developer portal, templates, automation.
4. **Compliance & Observability**: instrumentation, SLOs, anomaly detection, reporting.

## 3. Component Overview
| Component | Role | Notes |
| --- | --- | --- |
| HashiCorp Vault / Doppler | Secret management | Manage credentials for LLM, DB, providers. |
| Open Policy Agent (OPA/Gatekeeper) | Policy-as-code for deployments | Enforce model approval, data access.
| Backstage / DataHub UI | Developer portal | Surface datasets, features, models, agent catalog.
| Chaos Engineering Toolkit (Litmus) | Resilience testing | Simulate failures for Kafka, Ray, vLLM. |
| Multi-region Replication | Kafka MirrorMaker, MinIO replication | Support DR and region-specific workloads. |
| Service Mesh | Istio/Linkerd (future) | Zero-trust networking, mTLS, traffic policies. |
| CI/CD Extensions | GitOps with Argo CD or FluxCD | Manage infrastructure & model deployments. |
| Cost Monitoring | Kubecost equivalent or custom dashboards | Tie metrics to Cloud migration planning. |

## 4. Security & Compliance Plan
### 4.1 Secrets & Credentials
- Deploy Vault running in docker-compose or external (for production move). Store MinIO, PostgreSQL, LLM API keys, provider secrets.
- Update services to read secrets via Vault Agent sidecar or environment injection.
- Rotate secrets regularly; enforce TTL on tokens.

### 4.2 Policy Enforcement
- Define OPA policies:
  - `model_promotion.rego`: require approvals from ML lead + business owner before MLflow stage -> Production.
  - `agent_tool_usage.rego`: restrict certain tools (e.g., database writes) to approved agent personas.
  - `data_access.rego`: ensure datasets tagged `PII` only accessible to allowed roles.
- Integrate OPA in CI (GitHub Actions) and runtime (Kubernetes ingress) later.

### 4.3 Audit & Compliance
- Store all deployment metadata (model version, pipeline run, approval, change ticket) in DataHub + Git history.
- Use Airflow DAG to compile monthly compliance report (model usage, incidents, SLA stats) and send to stakeholders.
- Maintain model cards & agent cards in docs repository; link to DataHub entries.

## 5. Resilience & Scalability
### 5.1 Multi-Region Strategy
- Kafka: MirrorMaker 2 config to replicate critical topics (orders, payments, ml events) across regions.
- MinIO: enable bucket replication to secondary site; test failover.
- Databases: plan for read replicas & backups (MySQL binlog shipping, Postgres streaming replication, Cassandra multi-dc).

### 5.2 Backup & DR
- Schedule Airflow DAGs for snapshot/backup:
  - MinIO bucket snapshots (versioning + nightly backup to cold storage).
  - Postgres/MySQL dumps stored in MinIO `backups/` with retention policy.
  - Qdrant snapshot to MinIO.
- Run quarterly DR drills.

### 5.3 Chaos Engineering
- Introduce LitmusChaos (if using Kubernetes later) or `chaos-mesh` alternative. For current docker setup, use Toxiproxy/fault injection scripts.
- Scenarios: Kafka broker down, Ray worker crash, schema registry offline, LLM timeout.
- Document expected behavior and fallback (e.g., degrade gracefully to cached recommendation).

## 6. Self-Service Portal & Automation
- Adopt Backstage or extend DataHub UI to show service catalog: datasets, features, models, agents, pipelines.
- Provide templates (cookiecutter) for new microservices, data pipelines, models.
- Setup onboarding checklist for new teams (data contract creation, feature store onboarding, agent persona definition).
- Integrate with documentation (docs/design) via Backstage TechDocs.

## 7. Observability & SLOs
- Define SLOs:
  - Data pipeline SLA: Airflow DAG success within 15 min of schedule.
  - Model inference SLA: P95 < 100ms (reco), < 300ms (LLM).
  - Agent accuracy/hallucination SLO: < 5% flagged responses.
  - Data freshness: Feast materialization lag < 15 min.
- Use Prometheus + Grafana + Alertmanager for SLO burn rate alerts.
- Implement anomaly detection (AWS Lookout equivalent or custom) for business KPIs (revenue, conversion). Use MLflow/Evidently pipeline.

## 8. Tooling & Process Enhancements
- Expand GitHub Actions: add security scans (Trivy), dependency checks (pip-audit), ML metadata validation.
- Introduce Infrastructure-as-Code (Terraform) templates for migrating Compose services to Kubernetes (MinIO, Kafka, MLflow, Feast, Ray, Qdrant).
- Build runbooks for on-call: incident triage, rollback, data fix procedures.
- Align with FinOps: track resource usage, plan GPU capacity for LLM training/inference.

## 9. Backlog & Ownership
| ID | Task | Owner | Priority |
| --- | --- | --- | --- |
| ENT-01 | Deploy Vault (PoC) and migrate secrets | Platform | High |
| ENT-02 | Define OPA policies & integrate into CI | Platform | High |
| ENT-03 | Configure MirrorMaker & MinIO replication | Platform | High |
| ENT-04 | Implement backup DAGs (DB, MinIO, Qdrant) | Data Eng | High |
| ENT-05 | Establish SLO dashboards and alerts | Observability | High |
| ENT-06 | Create Backstage portal MVP | Dev Productivity | Medium |
| ENT-07 | Develop chaos scenarios & automation | Reliability | Medium |
| ENT-08 | Author compliance reporting DAG | Data Gov | Medium |
| ENT-09 | Produce IaC templates for K8s migration | Platform | Medium |

## 10. Roadmap Alignment
- Phase 4 tasks run in parallel with Phases 1-3 stabilization; some (Vault, SLOs) should start early.
- For implementation: after Phase 3 initial release, begin integrating Vault & OPA, then scale to multi-region & portal.

## 11. Next Steps
1. Evaluate Vault deployment options (container vs external) and plan secret migration.
2. Draft OPA policy definitions and integrate checks into GitHub Actions.
3. Prototype MirrorMaker replication between local brokers (docker) to validate config.
4. Build SLO dashboards & alert rules; review with stakeholders.
5. Plan Backstage adoption, identify plugins for DataHub, MLflow, Feast integration.
