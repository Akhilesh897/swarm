# SWARM Enterprise AI System: Technical Architecture

This document contains 7 comprehensive Mermaid diagrams illustrating the deepest technical mechanics of the SWARM repository, followed by an exhaustive repository file walkthrough.

## 1. High-Level System Architecture
This diagram outlines the macro-level services, the core API interface, and the division between the LangGraph execution engine, agent registries, and external persistence layers.

```mermaid
graph TD
    Client[Client / UI\nsrc/static/console.js] -->|HTTP / SSE| App[FastAPI App\nsrc/app.py]
    App -->|chat endpoint| Workflow[LangGraph Engine\nsrc/graph/workflow.py]
    App -->|PA webhooks| Auth[Auth / RBAC\nsrc/core/auth.py]
    
    Workflow --> Agents[Agent Registry\nsrc/agents/registry.py]
    
    Agents --> HRAgent[HR Agent\nsrc/agents/hr_agent.py]
    Agents --> ITAgent[IT Agent\nsrc/agents/it_agent.py]
    Agents --> RAGAgent[RAG Agent\nsrc/agents/rag_agent.py]
    Agents --> FinAgent[Finance Agent\nsrc/agents/finance_agent.py]
    
    HRAgent --> SQL[SQLite Service\nsrc/tools/sql.py]
    ITAgent --> SQL
    RAGAgent --> VectorStore[Vector Store\nsrc/tools/vector_store.py]
    
    SQL -.-> PowerAutomate[Power Automate Webhooks\nsrc/core/notifications.py]
    
    Workflow --> Synthesizer[Synthesizer\nsrc/core/generator.py]
    Synthesizer --> LLM[Groq / Gemini APIs]
```

## 2. LangGraph Orchestration Flow
This details the actual `GraphState` execution pipeline defined in `src/graph/workflow.py`. It shows the precise node sequence from intent classification down to final context persistence.

```mermaid
stateDiagram-v2
    [*] --> preprocess
    
    state preprocess {
        IntentClassifier(src/core/intent_classifier.py)
        ModelSelector(src/core/model_selector.py)
    }
    
    preprocess --> rbac
    
    state rbac {
        RBAC_Checks(src/core/rbac.py)
    }
    
    rbac --> synthesize : Access Denied
    rbac --> route : Access Granted
    
    state route {
        Router(src/core/router.py)
    }
    
    route --> agent
    
    state agent {
        HRAgent(hr_agent.py)
        ITAgent(it_agent.py)
        RAGAgent(rag_agent.py)
    }
    
    agent --> synthesize
    
    state synthesize {
        DynamicPrompt(src/core/generator.py)
        StreamingLLM(OpenAI/Groq Client)
    }
    
    synthesize --> memory
    
    state memory {
        MemoryManager(src/core/memory.py)
        ContextPersistence(app.db)
    }
    
    memory --> [*]
```

## 3. Complete Request Execution Flow (Streaming Enabled)
An end-to-end sequence diagram demonstrating how an HTTP request invokes the graph asynchronously, retrieves backend state, and streams Server-Sent Events (SSE) back to the user via `generator.py`.

```mermaid
sequenceDiagram
    participant User as Frontend (console.js)
    participant API as FastAPI (app.py)
    participant Graph as LangGraph (workflow.py)
    participant Agent as Specific Agent (e.g. it_agent.py)
    participant DB as SQLite (sql.py)
    participant PA as Power Automate (notifications.py)
    participant Gen as Synthesizer (generator.py)
    
    User->>API: POST /chat (stream=True)
    API->>Graph: run_graph(skip_synthesis=True)
    Graph->>Graph: preprocess (classify intent)
    Graph->>Graph: route (select agent)
    Graph->>Agent: handle(state)
    Agent->>DB: create_it_ticket_with_checks()
    DB-->>Agent: ticket_id, approval_id
    Agent->>PA: _notify_power_automate(payload)
    PA-->>Agent: HTTP 200 OK
    Agent-->>Graph: result (backend string)
    Graph-->>API: GraphState with raw response
    API->>Gen: generate_final_response(stream=True)
    Gen->>Gen: Build dynamic context prompt
    Gen-->>API: Yield tokens via Generator
    API-->>User: SSE chunks (data: {"chunk": "..."})
    API->>Graph: finalize_streaming_memory()
    Graph->>DB: memory_manager.save_long_term()
```

## 4. RAG Pipeline Flow
Visualizes the parallel pipelines for ingestion (run via background thread on startup) and retrieval (executed by the RAG agent).

```mermaid
graph TD
    subgraph Ingestion ["Ingestion Pipeline (src/tools/ingest.py)"]
        RawDocs["HR/IT Policy PDFs & MDs"] --> Chunker["Chunk Text & Overlap"]
        Chunker --> Metadata["Infer Section/Topic Metadata"]
        Metadata --> VStore["Vector Store\nsrc/tools/vector_store.py"]
        VStore -->|SentenceTransformers| Embeddings[("Chroma/Disk DB")]
    end
    
    subgraph Retrieval ["Retrieval Pipeline (src/agents/rag_agent.py)"]
        Query["User Query"] --> Intent["Intent Classifier\nIdentify Domain"]
        Intent --> Retriever["similarity_search\nvector_store.py"]
        Retriever -->|Retrieve Top K| Embeddings
        Embeddings -->|Context Chunks| PromptGen["Prompt Injector\nrag_agent.py"]
        PromptGen --> Generator["generator.py"]
        Generator --> Final["Final Humanized Response"]
    end
```

## 5. RBAC + Approval Workflow Diagram
Shows the hierarchical gatekeeping matrix implemented via `src/core/rbac.py` and the `sql.py` cascading approval engine.

```mermaid
stateDiagram-v2
    state "Employee Action" as EA
    state "Manager Approval Stage" as MA
    state "IT Lead Approval Stage" as IT
    state "Admin Bypass" as Admin
    
    EA --> MA : Request Leave / Asset
    
    state MA {
        Manager(manager_page)
        Action(approvals/action)
    }
    
    MA --> IT : Asset Approved (Next Stage)
    MA --> Finalized : Leave Approved / Rejected
    MA --> Rejected : Asset Rejected
    
    state IT {
        ITLead(it_lead_page)
        Inventory(check stock)
    }
    
    IT --> Finalized : Asset Approved/Rejected
    
    Admin --> Finalized : Direct Override (Any Stage)
```

## 6. Database + Service Interaction Diagram
Maps out the tight coupling between core service logic (`auth.py`, `sql.py`) and the underlying SQLite `app.db` relational schema.

```mermaid
graph TD
    subgraph Models ["Models & Security"]
        Auth["src/core/auth.py"] --> DB[("app.db SQLite")]
        Config["src/config.py"]
    end

    subgraph DataAccess ["Data Access Layer (src/tools/sql.py)"]
        Users["User CRUD & Identity"]
        Leaves["Leave Transactions"]
        Tickets["Ticket Lifecycle"]
        Assets["Asset Inventory"]
        Approvals["Approval Chains"]
    end

    Users --> DB
    Leaves --> DB
    Tickets --> DB
    Assets --> DB
    Approvals --> DB

    subgraph Agents
        HR["hr_agent.py"] --> Leaves
        IT["it_agent.py"] --> Tickets
        IT --> Assets
        IT -.-> Approvals
        HR -.-> Approvals
    end
```

## 7. Tool + FastMCP Interaction Diagram
Illustrates the exposed tool architecture (via `fastmcp_tools.py`) enabling external services or external AI models to interact securely with the SWARM API via Model Context Protocol interfaces.

```mermaid
graph LR
    subgraph FastAPI ["FastAPI Core"]
        Router["tools_router\nsrc/tools/fastmcp_tools.py"]
    end
    
    subgraph MCP ["MCP Endpoints"]
        GetTickets["get_tickets_mcp"]
        CreateTicket["create_ticket_mcp"]
        LeaveBalance["get_leave_balance_mcp"]
        ApplyLeave["apply_leave_mcp"]
        SearchRAG["search_kb_mcp"]
    end
    
    Router --> GetTickets
    Router --> CreateTicket
    Router --> LeaveBalance
    Router --> ApplyLeave
    Router --> SearchRAG
    
    GetTickets --> SQL["src/tools/sql.py"]
    CreateTicket --> SQL
    LeaveBalance --> SQL
    ApplyLeave --> SQL
    SearchRAG --> VStore["src/tools/vector_store.py"]
```

---

## Complete Repository Walkthrough & Architecture Explanation

### 1. The Core Infrastructure (`src/` and Root)
The repository uses a monolithic Python backend structured for a heavily decoupled agentic framework. 
* **`src/app.py`**: The central nervous system. It mounts the FastAPI application, serves the static HTML/CSS/JS files, and houses all explicit HTTP endpoints (`/chat`, `/auth/login`, `/tickets/my`, etc.). It natively supports **SSE (Server-Sent Events)** streaming.
* **`src/config.py`**: A centralized Pydantic settings module that dynamically maps API keys (`GROQ_API_KEY`) and endpoints from the root `.env` file.
* **`data/` & `app.db`**: SQLite database housing relational tables for users, roles, leaves, tickets, assets, approvals, and audit logs.
* **`src/static/`**: Vanilla JavaScript (`console.js`, `signup.js`), standard HTML (`console.html`, `index.html`), and pure CSS (`styles.css`). This was designed to be hyper-fast and entirely devoid of heavy frontend frameworks.

### 2. State & Memory Management (`src/core/`)
* **`memory.py`**: Manages short-term conversation context (`Session State`) and long-term history. It is highly pivotal because the LangGraph DAG resets state per turn; this module acts as the persistent brain.
* **`intent_classifier.py`**: An LLM-based router. Before any agent acts, this file hits the Groq API to extract JSON identifying: `is_question` (bool), `domain` (IT, HR, Finance, General), and `intent_type` (action, status, policy, casual).
* **`generator.py`**: The synthesis engine. This intercepts raw "robotic" responses from backend queries (like "Ticket 32 Assigned") and processes them into natural, empathetic, conversational AI responses.
* **`rbac.py`**: Role-Based Access Control matrix. This module halts execution if an `employee` requests to query `it_lead` data.

### 3. The LangGraph Engine (`src/graph/workflow.py`)
This is the execution topology. Instead of hardcoded `if/else` ladders, the system invokes `run_graph()`.
1. **`_preprocess`**: Invokes the intent classifier.
2. **`_rbac`**: Stops unauthorized requests.
3. **`_route`**: Pushes the context to `registry.py` to retrieve the correct Agent class.
4. **`_agent`**: Executes the deterministic Python logic.
5. *(Optional)* **`_synthesize`**: Bypassed if Streaming is active, otherwise invokes `generator.py` inline.
6. **`_memory`**: Saves entities (like mentioned Ticket IDs) back into memory.

### 4. The Agent Swarm (`src/agents/`)
Agents strictly inherit from `AgentBase` and define `handle(state)`.
* **`hr_agent.py` & `it_agent.py`**: They parse temporal data (e.g., "next Tuesday") using `date_parser.py`, and invoke strict SQL transactions via `src/tools/sql.py`.
* **`rag_agent.py`**: The fallback knowledge agent. It uses `vector_store.py` to semantically search embeddings for policy-related questions not covered by SQL transactions.

### 5. Tools & Persistence (`src/tools/`)
* **`sql.py`**: The single source of truth for transactions. All database calls (CRUD for users, tickets, approvals) live here. It manages the complex tiered approval chains (Manager -> IT Lead).
* **`ingest.py`**: Uses `pypdf` and text chunking to break down policy documents stored in `data/docs/`. It runs on a background daemon thread on startup (inside `app.py`) to prevent server blocking.
* **`fastmcp_tools.py`**: An adapter layer that exposes standard tool functions via the **Model Context Protocol**, making SWARM capabilities accessible to external automation tools.
