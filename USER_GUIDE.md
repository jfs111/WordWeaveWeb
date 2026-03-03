# ✦🕸️ Word Weave Web — User Guide

> Welcome! This guide walks you through using Word Weave Web, your intelligent document management platform.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Dashboard](#2-dashboard)
3. [Create a Project](#3-create-a-project)
4. [Step 1 — Upload Documents](#4-step-1--upload-documents)
5. [Step 2 — Automatic Clustering](#5-step-2--automatic-clustering)
6. [Step 3 — Relation Detection](#6-step-3--relation-detection)
7. [Step 4 — Explore the Corpus](#7-step-4--explore-the-corpus)
   - [Semantic Search](#71-semantic-search)
   - [Chat RAG](#72-chat-rag)
   - [Knowledge Graph](#73-knowledge-graph)
   - [Analyze a Document](#74-analyze-a-document)
8. [Account Management](#8-account-management)
9. [External API](#9-external-api)
10. [FAQ](#10-faq)

---

## 1. Getting Started

### Create an account

1. Open your browser and go to `http://localhost:8002`
2. Click **Create an account**
3. Enter your name, email, and password
4. You are redirected to the dashboard

### Log in

1. Go to `http://localhost:8002`
2. Enter your email and password
3. Click **Log in**

### Prerequisites for AI features

Some features require a **local LLM** (indicated by the "LLM connected" / "LLM disconnected" badge at the top of the page):

| Feature | LLM required? |
|---------|--------------|
| Document upload | No |
| Clustering | No |
| Semantic search | No |
| **Relation detection** | **Yes** |
| **Chat RAG** | **Yes** |
| **Document analysis** | **Yes** |

To connect the LLM: launch LM Studio (or Ollama) with a loaded model on port 1234.

---

## 2. Dashboard

The dashboard displays all your projects with their statistics at a glance.

### What you see

- **Project card**: name, description, document/chunk/relation counts
- **Status badge**: active (green) or processing (orange)
- **+ New project button**: create a new corpus

### Available actions

- Click a card to open the project
- Generate an API key (for external integration)
- Log out

---

## 3. Create a Project

1. From the dashboard, click **+ New project**
2. Fill in:
   - **Name**: short identifier (e.g., "GDPR", "Marketing Training")
   - **Description**: corpus summary (optional)
3. Click **Create**
4. You are redirected to the project page

### Default parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Chunk size | 1500 characters | Document splitting |
| Overlap | 200 characters | Overlap between chunks |
| Embedding model | paraphrase-multilingual-MiniLM-L12-v2 | Supports 50+ languages |
| Clustering method | Auto-K | Automatic cluster count detection |

---

## 4. Step 1 — Upload Documents

### How to upload

1. The **Upload** step is always active (pulsing blue circle)
2. Two options:
   - **Drag and drop** your PDF files into the upload zone
   - **Click** "Select files" or "Select a folder"
3. Documents are automatically processed: text extraction → chunking → embedding

### What happens behind the scenes

```
PDF uploaded → Text extraction (PyPDF2) → Chunking (1500 chars)
→ Embedding (384 dimensions) → Storage in Qdrant + PostgreSQL
```

### Processing status

- Documents appear in the list with their status:
  - 🟡 **processing**: being processed
  - 🟢 **processed**: ready
  - 🔴 **error**: problem (corrupted file, etc.)
- Counters (Documents, Chunks) update automatically every 5 seconds

### Supported formats

Currently: **PDF only**. Text is extracted automatically.

### When to move to the next step?

As soon as you have at least one document with chunks (status "processed"), the stepper unlocks step 2. Click **Next step →** or directly on the ② circle in the stepper.

---

## 5. Step 2 — Automatic Clustering

### What is it for?

Clustering groups your chunks by theme. Instead of browsing hundreds of chunks one by one, you get coherent groups (e.g., "data protection", "user rights", "sanctions").

### How to launch clustering

1. Click **🎯 Launch Auto-K Clustering**
2. The algorithm analyzes embeddings and automatically determines the optimal number of clusters
3. A progress bar shows the advancement
4. Result: the "Clusters" counter updates

### The Auto-K algorithm

Auto-K combines 3 metrics to find the best number of clusters:
- **Elbow** (30%): finds the inertia inflection point
- **Silhouette** (40%): measures separation between clusters
- **Davies-Bouldin** (30%): measures cluster compactness

You don't need to configure anything — it's fully automatic.

### Typical results

| Corpus size | Expected clusters |
|------------|------------------|
| < 50 chunks | 3 to 8 |
| 100-500 chunks | 10 to 35 |
| 500-1500 chunks | 20 to 50 |

### Processing time

Clustering is fast: a few seconds to one minute, even for 1000+ chunks.

---

## 6. Step 3 — Relation Detection

### ⚠️ Prerequisite: LLM connected

This step requires a local LLM. Check the "LLM connected" badge at the top of the page.

### What is it for?

The LLM analyzes pairs of chunks within each cluster to identify **semantic links** between them. This is what transforms your collection of isolated documents into a real **knowledge graph**.

### How to launch detection

1. Click **🔗 Detect Relations (LLM)**
2. The system analyzes cluster by cluster
3. The progress bar indicates "cluster X (Y/Z)"
4. The "Relations" counter increases in real time

### Detected relation types

| Type | Meaning | Example |
|------|---------|---------|
| PREREQUIS | A must be understood before B | "GDPR Definition" → "GDPR Sanctions" |
| COMPLEMENTAIRE | A and B enrich each other | "Individual rights" ↔ "Controller obligations" |
| SIMILAIRE | A and B cover the same topic | Two articles on consent |
| METHODOLOGIQUE | Methodological link | "SWOT Analysis" → "Marketing plan" |
| APPLICATION | A is an application of B | "Marketing theory" → "Case study" |
| EXEMPLE | A illustrates B | "GDPR principles" → "Compliance example" |
| SUITE_LOGIQUE | A follows B logically | Chapter 1 → Chapter 2 |
| TRANSVERSAL | Link between different domains | "Project management" ↔ "AI regulation" |
| AUTRE | Uncategorized relation | — |

### Processing time

Relation detection is the longest step because each pair is analyzed by the LLM:

| Corpus size | Estimated duration |
|------------|-------------------|
| < 100 chunks | 5-10 min |
| 400 chunks / 34 clusters | 40-60 min |
| 1000 chunks / 50 clusters | 1-2 hours |

💡 You can leave the page — processing continues in the background. Come back later to see the results.

---

## 7. Step 4 — Explore the Corpus

The Explorer step contains 4 sub-tabs to interact with your enriched corpus.

### 7.1 Semantic Search

**🔍 "Search" tab**

Type a question or topic in the search field. The system:
1. Converts your query to a vector (embedding)
2. Finds the most similar chunks in Qdrant
3. **Enriches** results using the relation graph

#### "Graph enrichment" option

- **Enabled** (default): results include chunks linked by the graph, even if they're not directly similar to your query. Richer results.
- **Disabled**: purely vector-based search (faster, less rich).

#### Reading a result

Each result displays:
- The chunk text (excerpt)
- The source document (clickable)
- The similarity score (%)
- The cluster membership

### 7.2 Chat RAG

**💬 "Chat RAG" tab**

Ask a question in natural language. The LLM generates a structured answer based on your corpus.

#### How it works

```
Your question → Semantic search → Relevant chunks → LLM generates an answer
→ Structured response with tables + cited sources
```

#### Features

- **Formatted answers**: tables, lists, headings — automatic layout
- **Cited sources**: each answer displays source documents with their relevance score
- **Graph enrichment**: check the option to include relations in context (richer answers)
- **Reformat**: button to reformat an answer if needed

#### Examples of effective questions

| ✅ Good question | ❌ Less effective question |
|-----------------|--------------------------|
| "What are the steps of a marketing campaign?" | "Marketing" |
| "How to measure ad effectiveness?" | "KPI" |
| "What are individual rights under GDPR?" | "rights" |
| "Compare agile and waterfall approaches" | "agile" |

💡 The more specific and complete your question, the better the answer.

### 7.3 Knowledge Graph

**🕸️ "Graph" tab**

Interactive visualization of the relation network between your documents.

#### Navigation

- **Zoom**: mouse wheel
- **Pan**: click-drag on the background
- **Select a node**: click on a circle → shows chunk details
- **Filter by type**: dropdown to display only one relation type
- **Filter by cluster**: view only chunks from one cluster

#### Color legend

- Each **cluster** has a unique color
- **Lines** between nodes represent relations
- Line thickness = relation intensity

#### Tooltip on hover

Hover over a node to see:
- Source document title
- Cluster membership
- Number of relations
- Text excerpt

### 7.4 Analyze a Document

**🔬 "Analyze a doc" tab**

Upload a **new PDF** to analyze it against your existing corpus. The system automatically detects which clusters and documents it relates to.

#### How to launch an analysis

1. Drag a PDF into the upload zone or click "Select a file"
2. Click **🚀 Launch analysis**
3. The pipeline executes (extraction → chunking → embedding → clusters → LLM relations)
4. A Markdown report is displayed with:
   - Summary (pages, chunks, clusters, relations)
   - Distribution by cluster (table)
   - Detail of each detected relation with LLM justification
   - Synthesis and related reference documents

#### ⚠️ Prerequisites

- LLM connected (for relations and synthesis)
- At least one clustering performed on the corpus

#### Use cases

- **Compliance**: "Is this new document compliant with my GDPR reference framework?"
- **Training**: "How does this course fit into my RNCP program?"
- **Monitoring**: "Does this report have links to our document base?"

---

## 8. Account Management

### From the dashboard

- **View your profile**: name, email, plan (free/pro/enterprise)
- **Generate an API key**: click "Generate API key" to get a `gr_xxxxx` key
- **Log out**: button at the bottom of the sidebar

### Plans and quotas

| Plan | Projects | Documents | Storage |
|------|----------|-----------|---------|
| Free | 3 | 100 / project | 500 MB |
| Pro | 20 | 5,000 / project | 50 GB |
| Enterprise | Unlimited | Unlimited | Unlimited |

---

## 9. External API

To integrate Word Weave Web into your tools (AI agents, scripts, applications), use the REST API.

### Authentication

Add your API key in the header:

```
X-API-Key: gr_xxxxx
```

### Main endpoints

```bash
# List your projects
GET http://localhost:8002/api/v1/projects

# Semantic search
POST http://localhost:8002/api/v1/search
Content-Type: application/json
{"query": "data protection", "project_id": "xxx", "n_results": 10}

# Chat RAG
POST http://localhost:8002/api/v1/chat
Content-Type: application/json
{"query": "Summarize GDPR obligations", "project_id": "xxx"}

# Full graph
GET http://localhost:8002/api/v1/projects/{id}/graph

# Project stats
GET http://localhost:8002/api/v1/projects/{id}/stats
```

### Python example

```python
import requests

API_URL = "http://localhost:8002/api/v1"
headers = {"X-API-Key": "gr_your_key"}

# Search
response = requests.post(f"{API_URL}/search", headers=headers, json={
    "query": "GDPR sanctions",
    "project_id": "your-project-id",
    "n_results": 5
})
results = response.json()
for r in results:
    print(f"[{r['score']:.0%}] {r['document']} — {r['text'][:100]}...")
```

---

## 10. FAQ

### Clustering produces very few clusters — is this normal?

If you have few documents or your corpus is very homogeneous, Auto-K may find a low number of clusters. This is normal — it optimizes group quality over quantity.

### Relations take a very long time — can I leave the page?

Yes. Processing continues in the background. Come back whenever you want — progress will update automatically.

### The LLM is disconnected — what should I do?

1. Check that LM Studio (or Ollama) is running
2. Check that a model is loaded
3. Check that the server is listening on port 1234
4. The indicator in the interface updates every 30 seconds

### Can I upload something other than PDF?

For now, only **PDF** files are supported. Word, text, and HTML files are planned for a future version.

### How do I delete a document in error?

Currently, deletion is done via the database. Contact the administrator or use the command:
```bash
docker exec -it graphrag-postgres psql -U graphrag -d graphrag -c "DELETE FROM documents WHERE filename='my_file.pdf';"
```

### Are search results better with or without graph enrichment?

**With** the graph enabled, results are richer because the system includes chunks linked by semantic relations (even if they're not directly similar to your query). This is recommended for complex questions. For simple, precise questions, disable it for more focused results.

### What's the difference between Search and Chat RAG?

- **Search**: returns the most relevant raw chunks (no LLM generation)
- **Chat RAG**: generates a structured natural language answer from relevant chunks (requires the LLM)

### How many documents can I upload?

This depends on your plan. On the Free plan: 100 documents per project, 500 MB storage. See quotas in the [Account Management](#8-account-management) section.

---

*✦🕸️ Word Weave Web — Weaving the links between your documents.*