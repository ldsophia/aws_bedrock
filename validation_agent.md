# Validation Agent — Design Document

## 1) Problem Statement
Modern AI workflows (BYOW: Build Your Own Workflow) ingest extracted data from OCR, scrapers, ETL jobs, and LLMs. Downstream systems require this data to be correct, complete, and consistent with authoritative sources (APIs, desktop line-of-business apps, and databases). Today, validation logic is scattered across scripts and services, is hard to reuse, and provides limited observability. We need a reusable **Validation Agent node** that can be dropped into any workflow to declaratively validate extracted data, reconcile against external systems, and produce explainable results with strong monitoring and auditability.

## 2) Goals & Non‑Goals
**Goals**
- Provide a single node that performs schema, rule-based, and cross-system validation.
- Support simple checks directly with LLMs (natural-language rules, fuzzy matching) and complex checks via tools (API/DB/RPA desktop actions).
- Emit machine-readable validation results, human-readable summaries, and structured logs for monitoring.
- Be configurable by drag‑and‑drop and via JSON/YAML definitions (import/export), enabling reuse.
- Offer explainability (why a rule passed/failed) and deterministic re-runs.

**Non‑Goals**
- Implement source extraction itself.
- Own data remediation/auto-fix actions (may suggest fixes, remediation handled by other nodes).
- Replace full-featured test frameworks; this is runtime data validation.

## 3) Scope
**In Scope**
- Field-level checks: required/not-null, type, pattern/format, ranges, enumerations, uniqueness (within batch/collection), conditional rules (IF/THEN), cross-field constraints, temporal constraints.
- Record- and batch-level checks: duplicates, referential integrity (foreign keys), distribution/outlier detection.
- Cross-system validation: compare extracted values with authoritative values from APIs, databases, or desktop apps (via RPA/agent tools).
- LLM-assisted validation for semantic equivalence, fuzzy normalization, and unstructured-to-structured consistency.
- Tool orchestration, retries, timeouts, backoff, and circuit breaking.
- Observability: metrics, traces, logs, lineage, per-check evidence artifacts.

**Out of Scope**
- Long-running background monitoring outside the workflow run.
- Data masking/tokenization (supported via pre/post-processing hooks, not owned).

## 4) Personas & Primary Use Cases
- **Ops Integrator:** Assembles workflows, configures checks, maps tools.
- **Data Steward:** Reviews failures, needs explanations and exportable reports.
- **Auditor/Compliance:** Requires immutable evidence and policy alignment.

Use cases include invoice extraction QA, KYC document verification, product catalog sync, claims adjudication, and shipment status reconciliation.

## 5) Architecture Overview
```
+---------------------------+
| Validation Agent Node     |
|---------------------------|
| • Policy Engine           |
| • Rule Evaluator          |
| • LLM Checker             |
| • Tool Orchestrator       |
| • Evidence Store          |
| • Reporter & Logger       |
+-----+----------+----------+
      |          |
  Input Data   Tool Registry (API, DB, Desktop/RPA, Files)
      |
  Output Results (JSON), Events, Metrics
```

**Key Components**
- **Policy Engine:** Compiles declarative rules, resolves precedence, and binds data to checks.
- **Rule Evaluator:** Executes deterministic checks (schema, regex, range, SQL constraints).
- **LLM Checker:** Uses prompts to verify semantic/format rules when deterministic checks are insufficient.
- **Tool Orchestrator:** Runs external actions (HTTP, SQL, desktop automation), manages auth, retries, and caching.
- **Evidence Store:** Persists inputs, responses, and diffs for explainability/audit.
- **Reporter & Logger:** Emits results, metrics, and alerts; integrates with platform monitor.

## 6) Key Features
1. **Declarative Validation Rules** (per field/record/batch) with priorities and severities (INFO/WARN/ERROR).
2. **Hybrid Validation**: choose LLM vs. tools per rule; fallbacks if a method fails.
3. **External System Assertions**: lookup by key and compare (exact, tolerance, semantic, mapping table).
4. **Desktop App Validation**: through RPA/desktop tool adapters (selector definitions, screen parsing, OCR hooks).
5. **Database Validation**: parameterized SQL with safe templating; connection pooling; row-level evidence capture.
6. **API Validation**: REST/gRPC/SOAP connectors; schema validation; authentication profiles; idempotent replays.
7. **Configurable Tolerances & Matching Strategies**: exact, case-insensitive, regex, numeric tolerance, date slack, semantic equivalence.
8. **Sampling & Stratification** for large batches; adaptive sampling based on historical risk.
9. **Explainability**: per-check rationale, inputs, external responses, and diffs.
10. **Observability & SLAs**: latency, success rates, external call error rates, saturation, rule hit distributions.
11. **Policy Packs**: reusable bundles (e.g., PII completeness, address normalization, invoice rules).
12. **Role-Based Access**: least-privilege credentials per tool; secrets via platform vault.
13. **Dry-Run Mode**: evaluate rules without committing side effects; generate full report.
14. **Auto-Remediation Hooks**: emit actions/suggestions (e.g., “normalize date”; “re-query with alt key”).
15. **Versioning**: immutable rule versions; attach run to version for audit.

## 7) Inputs & Outputs
### 7.1 Agent Input Schema (JSON)
```json
{
  "run_id": "<uuid>",
  "data": [
    { "record_id": "rec-001", "payload": {"invoice_id": "INV-123", "amount": 199.99, "date": "2025-10-01", "supplier_vat": "GB123456789"} }
  ],
  "schema": {
    "fields": [
      {"name": "invoice_id", "type": "string", "required": true, "unique": true, "pattern": "^INV-[0-9]+$"},
      {"name": "amount", "type": "number", "required": true, "range": {"min": 0, "max": 100000}},
      {"name": "date", "type": "date", "required": true, "range": {"min": "2020-01-01", "max": "now"}},
      {"name": "supplier_vat", "type": "string", "required": true, "format": "VAT_GB"}
    ]
  },
  "rules": [
    {"id": "r1", "level": "record", "severity": "ERROR", "type": "not_null", "field": "invoice_id"},
    {"id": "r2", "level": "field", "severity": "ERROR", "type": "pattern", "field": "invoice_id", "pattern": "^INV-[0-9]+$"},
    {"id": "r3", "level": "batch", "severity": "ERROR", "type": "unique", "field": "invoice_id"},
    {"id": "r4", "level": "record", "severity": "WARN", "type": "range", "field": "amount", "min": 0},
    {"id": "r5", "level": "record", "severity": "ERROR", "type": "cross_system", "lookup": {"tool": "erp_api", "method": "GET", "path": "/invoices/{invoice_id}", "key_map": {"invoice_id": "payload.invoice_id"}}, "assert": {"path": "$.amount", "operator": "≈", "tolerance": 0.01, "compare_to": "payload.amount"}},
    {"id": "r6", "level": "record", "severity": "WARN", "type": "llm_semantic", "prompt": "Does the line-item total equal the header amount allowing for rounding?", "inputs": {"text": "payload"}}
  ],
  "tools": [
    {"name": "erp_api", "type": "http", "base_url": "https://erp.example.com", "auth_profile": "erp_oauth"},
    {"name": "legacy_db", "type": "sql", "driver": "postgres", "conn_ref": "db_ledger"},
    {"name": "desktop_app", "type": "rpa", "profile": "legacy_client"}
  ],
  "runtime": {"timeouts_ms": {"rule_default": 10000, "tool_default": 15000}, "retries": 2, "circuit_breakers": {"enabled": true, "error_rate_threshold": 0.25}},
  "output_prefs": {"format": "detailed", "include_evidence": true}
}
```

### 7.2 Agent Output Schema (JSON)
```json
{
  "run_id": "<uuid>",
  "summary": {"records": 1, "errors": 1, "warnings": 1, "passes": 5},
  "results": [
    {
      "record_id": "rec-001",
      "checks": [
        {"rule_id": "r1", "status": "PASS"},
        {"rule_id": "r2", "status": "PASS"},
        {"rule_id": "r3", "status": "PASS"},
        {"rule_id": "r4", "status": "PASS"},
        {"rule_id": "r5", "status": "FAIL", "evidence": {"request": {"url": "https://erp.example.com/invoices/INV-123"}, "response": {"amount": 199.49}, "diff": {"expected": 199.99, "actual": 199.49, "operator": "≈", "tolerance": 0.01}}, "explanation": "ERP amount differs beyond tolerance"},
        {"rule_id": "r6", "status": "WARN", "llm": {"model": "gpt-x", "answer": "Totals likely match within rounding."}}
      ]
    }
  ],
  "artifacts": {"report_url": "urn://artifact/report/…", "evidence_refs": ["urn://evidence/…"]},
  "metrics": {"latency_ms": 2320, "tool_calls": 1, "llm_calls": 1}
}
```

## 8) Agent Request Definition (Copilot‑style)
**Agent Name:** ValidationAgent

**Input Prompt Template**
- System: “You validate structured records using rules and external tools. Return machine-readable results and concise human explanations.”
- User template: “Validate the following payload(s) with the provided schema and rules. Return failures with evidence.”

**Configurable Parameters**
- `model_profile`: default LLM, temperature, max_tokens.
- `tool_policies`: allowed tools, rate limits, auth profiles.
- `timeouts_ms`, `retries`, `concurrency_limit`.
- `privacy`: redact fields (PII), drop raw responses.
- `explainability_level`: none | brief | detailed.

**Tools** (registry-bound)
- `http.request`, `sql.query`, `rpa.desktop`, `file.lookup`, `kv.cache`.

**Result Contract**
- `status`: PASS | WARN | FAIL | INCOMPLETE.
- `checks[]`: per-rule outcomes, evidence URNs, explanations, timings.
- `usage`: tokens, tool-call counts, costs (if available).

## 9) Activity Map (Execution Flow)
1. **Initialize**: load config, bind tools, open evidence session.
2. **Pre-Validation**: schema/type coercion; optional normalization (trim, case, date formats).
3. **Plan**: compile rules → execution plan (group by level, tool needs, parallelizable sets).
4. **Execute Deterministic Checks**: not-null, unique, range, regex, enum, conditional.
5. **Select Strategy per Rule**:
   - If rule is `cross_system`: call Tool Orchestrator.
   - If rule is `llm_semantic`: call LLM Checker; otherwise skip.
   - If deterministic operator available, prefer deterministic; use LLM as fallback.
6. **External Calls**: HTTP/SQL/RPA with caching, retries, circuit-breaking.
7. **Compare & Decide**: evaluate operator (==, !=, ≈, ⊂, regex, JMESPath/JSONPath expressions, UDFs).
8. **Record Evidence**: inputs, sanitized outputs, diffs, screenshots (desktop), SQL rows.
9. **Aggregate**: compute record/batch summaries; severities to overall status.
10. **Report**: produce JSON output and human summary; emit events/metrics.

## 10) Tool Selection Logic (Decision Rules)
- **Deterministic First**: If a rule can be expressed as type/range/regex/SQL, run deterministically.
- **External if Authoritative**: If a reliable system of record exists, use its tool connector.
- **LLM When Ambiguous**: Use for fuzzy/semantic equivalence, unstructured text checks, or heuristic thresholds.
- **Cost/Latency Aware**: Prefer cached/memoized responses; degrade to LLM only if cheap deterministic checks pass inconclusively.
- **Policy Guardrails**: Deny tools not approved for this run; enforce rate limits and PII redaction.

## 11) Monitoring & Logs
**Event Types**
- `validation.run.started|completed|failed`
- `tool.call.started|completed|error`
- `rule.check.started|completed`

**Structured Log Fields**
- `run_id`, `rule_id`, `record_id`, `severity`, `status`, `latency_ms`, `tool_name`, `retries`, `error_code`, `evidence_ref`.

**Metrics (per run & sliding windows)**
- Success/Fail/Warn rates; mean/95p latency; tool error rate; LLM token usage; rule hit histogram; cache hit ratio.

**Dashboards**
- Run health (SLOs), Top failing rules, External dependency health, Cost overview.

**Alerts**
- Circuit breaker open; spike in FAIL rate; tool auth failures; unexpected schema drift.

## 12) Security & Compliance
- **Auth**: short‑lived tokens, per-tool credentials from platform vault.
- **PII Handling**: field-level redaction in logs; configurable deny-lists.
- **Evidence Retention**: TTLs per artifact type; WORM mode for audits.
- **Least Privilege**: read-only DB roles for validation; scoped API keys.

## 13) Performance & Scalability
- Parallel rule groups with max concurrency.
- Request coalescing and memoization for repeated lookups.
- Adaptive sampling for large batches.
- Backpressure: queue with bounded inflight tool calls.

## 14) Error Handling & Resilience
- Rule-level timeouts and retries with jittered backoff.
- Partial results with `INCOMPLETE` when external systems unavailable.
- Circuit breaker per tool; fallback strategies (e.g., cached snapshot, LLM heuristic with WARN severity).

## 15) Configuration Model (YAML Excerpt)
```yaml
version: 1
agent: ValidationAgent
model_profile: default-llm-v1
timeouts_ms:
  rule_default: 10000
  tool_default: 15000
rules:
  - id: not_null_invoice
    type: not_null
    field: invoice_id
    severity: ERROR
  - id: uniq_invoice
    type: unique
    field: invoice_id
    level: batch
    severity: ERROR
  - id: api_amount_match
    type: cross_system
    severity: ERROR
    lookup:
      tool: erp_api
      method: GET
      path: /invoices/{invoice_id}
    assert:
      path: $.amount
      operator: approx
      tolerance: 0.01
      compare_to: payload.amount
```

## 16) Operators & Expressions
- `==`, `!=`, `>`, `<`, `>=`, `<=`, `≈ (approx)`, `contains`, `in`, `regex`, `empty`, `not_empty`, `len`, `between`, `subset`, `superset`.
- Path selectors: JSONPath/JMESPath for nested payloads.
- UDFs: optional sandboxed functions (e.g., `iban_checksum`, `vat_checksum`).

## 17) Desktop/RPA Validation Notes
- Element locator strategies (id, name, xpath-like), action scripts, and screenshot capture on mismatch.
- Text extraction via accessibility APIs or OCR as evidence.
- Idempotent, read-only playbooks for validation.

## 18) Example: DB Cross-Check Rule
```json
{
  "id": "r_db1",
  "type": "cross_system",
  "severity": "ERROR",
  "lookup": {"tool": "legacy_db", "sql": "SELECT amount FROM ledger WHERE invoice_id = :invoice_id", "params": {":invoice_id": "payload.invoice_id"}},
  "assert": {"path": "$.rows[0].amount", "operator": "==", "compare_to": "payload.amount"}
}
```

## 19) Explainability & Evidence
- For each check, store: rule snapshot, inputs, tool responses (redacted), computed diffs, and rationale.
- Human summary: grouped by rule → top offending records with suggested fixes.

## 20) Testing Strategy
- Golden sample datasets for PASS/FAIL/WARN.
- Mock tool connectors; chaos tests (timeouts, 500s, auth failures).
- Schema drift tests; regression suites tied to rule versioning.

## 21) Roadmap & Extensions
- Learned anomaly detectors to auto-suggest new rules.
- Active learning loop: steward labels → rule refinements.
- Native address/identity normalization packs.
- Graph constraints for referential integrity across entities.

---
**Deliverables**: Agent node manifests (JSON/YAML), dashboards, and sample policy packs.
**Success Metrics**: ≥95% precision on true failures, ≥99% recall on critical constraints, p95 latency < 3s/record for deterministic checks, < 10% LLM usage on average with caching.

