# NimbusAI — GPU Cost Optimization Report

**Author:** Dam Quang Son (2A202602868)  
**Period:** monthly (June 2026 snapshot)  
**Date:** 2026-10-13  

---

## 1. Executive Summary

- **Baseline spend:** $27,133/month
- **Optimized spend:** $14,626/month
- **Projected savings:** $12,507/month (**46%**)
- **Inference Unit Economics:** $6.488 -> $1.126 per 1M tokens (**82.6% reduction**)

| Metric | Baseline | Optimized | Savings (USD) | Savings (%) |
|---|---|---|---|---|
| **Total Monthly Spend** | $27,133 | $14,626 | $12,507 | **46%** |
| **Cost / 1M Tokens** | $6.488 | $1.126 | $5.362 / 1M | **82.6%** |

---

## 2. Savings Breakdown by FinOps Lever

| Lever | Monthly Savings (USD) | Share of Savings (%) | Primary Mechanism |
|---|---|---|---|
| **Inference (cascade/cache/batch)** | $1,212 | 9.7% | Model cascading (small tier), 90% prompt caching, 50% batch discount |
| **Purchasing (spot/reserved)** | $10,040 | 80.3% | Spot instances for interruptible jobs, 1yr/3yr reserved for steady workloads |
| **Right-size util-lies** | $655 | 5.2% | Downgrade over-provisioned GPUs (H100 -> A100) stalled on memory/kernels |
| **Kill idle GPUs** | $600 | 4.8% | Auto-terminate idle compute (e.g. 8h/day idle H100) |
| **Total** | **$12,507** | **100.0%** | |

---

## 3. GPU-Util Lie & Telemetry Efficiency Audit

Traditional cloud monitoring often relies solely on `gpu_util_pct` (from `nvidia-smi`), which measures the fraction of time *any* kernel was executing on the GPU. This metric conceals critical waste.

### Flagged GPU-Util Lie Instances: `gpu-h100-4`, `gpu-a10g-1`

| GPU ID | Model | Reported Util (%) | MFU (Model FLOPs Util) | MBU (Memory Bandwidth Util) | Diagnosis |
|---|---|---|---|---|---|
| `gpu-h100-4` | H100 | 98.2% | 19.4% | 20.7% | Severe kernel launch overhead & memory stalls |
| `gpu-a10g-1` | A10G | 96.9% | 26.8% | 30.2% | Sub-optimal batching & tensor core idle |

### Root Cause & Mechanism Explanation
- **Why 98% Util vs 19% MFU?** `nvidia-smi` samples kernel execution in time slices. If a thread waits for high-bandwidth memory (HBM3) or spends time launching micro-kernels, the GPU is considered 'busy' even though matrix tensor cores are idling. Only 19.4% of peak FLOPs are actually being achieved.
- **Financial Impact:** An H100 costs $3.50/hr on-demand ($2,520/month). At 19.4% MFU, NimbusAI pays full H100 pricing while receiving compute throughput comparable to an A100 ($2.50/hr). Right-sizing saves **$655/month** directly.
- **Idle GPU Waste:** Telemetry flagged `gpu-h100-5` idling for 8 hours/day with 0% compute, causing $20.00/day = **$600/month** in waste. Immediate fix: enforce a 15-minute auto-termination policy.

---

## 4. Inference Optimization: Cascade, Cache & Batch

- **Model Cascading:** 70%+ of simple user requests are routed to small models ($0.20/1M tokens) instead of the default large model ($3.00/1M tokens).
- **Prompt Caching:** Shared system prompts and conversation context receive a 90% cache discount ($0.30/1M vs $3.00/1M on large; $0.02/1M vs $0.20/1M on small). Cache hit rate reached 31.9%.
- **Batch API:** Asynchronous jobs receive a 50% discount.
- **Net Impact:** Inference cost dropped from $48.87/day to $8.48/day, producing **$1,212/month in savings** and lowering cost per 1M tokens from $6.488 to $1.126.

---

## 5. Purchasing Strategy: Spot vs. Reserved Commitments

- **Break-even Threshold:** At a 45% reserved discount, break-even duty cycle is `1 - 0.45 = 55%` (~13.2h/day).
- **Spot Allocation:** 5 interruptible workloads (`job-train-llm`, `job-train-embed`, `job-finetune`, `job-dev-sandbox`, `job-batch-eval`) are moved to Spot with checkpointing, yielding substantial savings despite rework/overhead.
- **Reserved Allocation:** 3 steady workloads (`job-infer-chat`, `job-infer-rag`, `job-infer-search`) run 18-24h/day (well above 55% duty cycle) and are committed to Reserved instances.
- **Net Impact:** Monthly GPU instance spend reduced from $25,667 to $15,627 (**$10,040/month saved, 39.1%**).

---

## 6. Sustainability & Environmental Metrics

- **Energy per query:** 0.24 Wh
- **Carbon per query (us-east-1 baseline):** 0.091 gCO2e
- **Cheapest & cleanest region:** `europe-north1`

### Regional Grid Carbon Intensity Comparison
| Region | Location | Carbon Intensity (gCO2/kWh) | Emission Relative to Cleanest |
|---|---|---|---|
| `europe-north1` | Hamina, Finland | ~20 gCO2/kWh | **1.0x (Cleanest)** |
| `us-west-1` | Oregon, USA | ~90 gCO2/kWh | 4.5x |
| `us-east-1` | N. Virginia, USA | ~379 gCO2/kWh | 18.9x |
| `europe-central2` | Warsaw, Poland | ~650 gCO2/kWh | 32.5x |

**Sustainability Recommendation:** Relocating batch training workloads from `us-east-1` to `europe-north1` eliminates over **94%** of carbon emissions with zero user-facing latency impact.

---

## 7. FinOps Lead Prioritized Action Plan

To capture the $12,507/month (46%) savings, implement the following prioritized roadmap:

1. **Day 1 — Enable Gateway Inference Levers (ROI: Immediate, Risk: Low)**
   - Implement prompt caching and cascading via LiteLLM proxy.
   - Captures $1,212/month immediately without cloud infrastructure changes.

2. **Day 2 — Auto-Terminate Idle GPUs & Right-Size Util-Lies (ROI: Instant, Risk: Zero)**
   - Enforce 15-minute idle cull on `gpu-h100-5` (saves $600/month).
   - Downgrade `gpu-h100-4` to A100 (saves $655/month).

3. **Week 1 — Implement Spot & Reserved Purchasing Portfolio (ROI: Highest, Risk: Managed)**
   - Switch 5 batch/training jobs to Spot with automated checkpointing.
   - Purchase 1yr/3yr Reserved instances for 24/7 inference workloads.
   - Secures the single largest savings lever: **$10,040/month**.

4. **Month 1 — Cost Governance via FOCUS & Chargeback (Governance)**
   - Enforce 92%+ tag coverage across all engineering teams.
   - Implement chargeback gates preventing untagged workloads from launching.

---

_Figures are June-2026 as-of snapshots; re-baseline before acting._