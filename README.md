# Warehouse Safety Expert Agent: From Prototype to Production

This repository tracks the evolutionary lifecycle of building an Enterprise-Grade GenAI Agent using the **Google Agent Development Kit (ADK)**, **Gemini 2.5 Flash**, and **Google Cloud Platform**. 

The goal of this project is not just to "build a chatbot." It is to demonstrate the strict progression from a local, hacky prototype to a secure, containerized, A2A-compliant microservice ready for Gemini Enterprise integration.

> **NOTE TO CEs & ARCHITECTS:** 
> Developing GenAI on corporate infrastructure (like Google Cloudtop) means navigating BeyondCorp proxies, mTLS handshakes, and strict Workload Identity rules. This repository documents the "scar tissue" and the solutions needed to build cleanly in a zero-trust environment. Weigh whether you want to use managed "black box" low-code tools, or master this "Full-Code" path. It is challenging, but gives you total control over latency, security, and BigQuery costs. *Feel the power.*

---

## 🗺️ Repository Structure & Progression

This project is divided into progressive stages (`v0`, `v1`, etc.). Each folder represents a distinct step up in architectural maturity, building upon the lessons of the previous version.

```text
warehouse-safety-agent/
├── README.md                 # You are here (The Architectural Map)
├── v0-local-prototype/       # Stage 0: Core Logic & The Cloudtop Auth Maze
│   ├── main.py
│   ├── pyproject.toml
│   └── README.md             # In-the-weeds guide for v0 setup
└── v1-dockerized/            # Stage 1: Production A2A & Cloud Run
    ├── main.py               # Refactored for `to_a2a()`
    ├── Dockerfile
    ├── cloudbuild.yaml
    └── README.md             # In-the-weeds guide for Docker/Cloud Run
```

---

## 🏗️ Stage 0: Local Prototyping (`v0-local-prototype`)
**Goal: Prove the logic, tame the environment.**

In **v0**, we focus entirely on making the core Python code work on a secure Google Cloudtop using `uv` for lightning-fast dependency management. We write a massive chunk of custom boilerplate to manually intercept async event streams, parse Pydantic models, and construct the Agent's reasoning loop (CRAWL/WALK/RUN).

**Key Learnings in v0:**
1.  **The "Golden Workflow" of Identity:** Navigating the split between Internal Identity (LOAS/`gcert`) and Cloud Identity (ADC / `gcloud auth application-default login`).
2.  **BeyondCorp mTLS Fixes:** Forcing the Google Auth library to use standard TLS (`GOOGLE_API_USE_CLIENT_CERTIFICATE=false`) to prevent gLinux proxy crashes.
3.  **The Limits of Monoliths:** Recognizing that manually managing JSON-RPC envelopes and `InMemorySessionService` is too fragile for real production scale.

➡️ *See `v0-local-prototype/README.md` for local setup commands, `glogin` fixes, and git hygiene.*

---

## 🚀 Stage 1: Production A2A & Dockerization (`v1-dockerized`)
**Goal: Secure deployment, Agent-to-Agent (A2A) integration, and Zero-Trust constraints.**

In **v1**, we throw away the manual FastAPI boilerplate from v0 and replace it with the Google ADK's native `to_a2a()` wrapper. This dynamically generates a compliant A2A microservice. We then package it into a multi-stage Docker container and deploy it securely to Google Cloud Run.

**Key Upgrades in v1:**
1.  **The `to_a2a()` Magic:** Seamlessly handling deeply nested A2A JSON envelopes, auto-translating structured outputs, and automatically generating the `.well-known/agent-card.json` for Gemini Enterprise discovery.
2.  **The Google Container Contract:** Architecting the `Dockerfile` to respect dynamic `$PORT` binding, stateless execution, Workload Identity, and non-root user execution (`USER appuser`).
3.  **Cloud Build & IAM:** Moving from local execution to automated Cloud Build pipelines, and securely binding the Discovery Engine Service Agent to invoke our private Cloud Run service.

➡️ *See `v1-dockerized/README.md` for the exact Dockerfile, IAM bindings, and Gemini Enterprise registration JSON.*

---

## 🔮 What's Next (Future Iterations)
The architecture documented here serves as the foundation for true Enterprise AI. Future iterations built on this chassis will include:
*   **Persistent State:** Swapping `InMemorySessionService` for `VertexAiSessionService` backed by Firestore/BigQuery.
*   **Hardware Integration:** Connecting the Custom MCP Tools to real-time IoT edge streams (e.g., NVIDIA Jetson telemetry) instead of hardcoded mock data.
*   **RAG:** Grounding the agent in official Warehouse Safety compliance documents via Vertex AI Search. 

---
*Built with a vision for production. No black boxes. No low-code limits.*
