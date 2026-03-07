# 📂 Examples — Test Corpora & Benchmarks

This directory contains sample corpora and benchmark results to demonstrate Word Weave Web's Graph-RAG capabilities.

## Corpora

### `corpus_novatech/` — Enterprise Documentation (40 PDFs)
A fictional company (NovaTech Solutions SAS) with 40 interlinked documents: bylaws, internal regulations, IT charter, GDPR policy, security policy (PSSI), employment contracts with amendments, telework agreements, incident procedures, risk management plans, CSE minutes, and more.

**Why this corpus?** Documents have rich cross-references and amendment chains (e.g., Contract → Amendment 1 → Amendment 2, Policy → Procedure → Incident Response → Risk Plan). This is where **Graph-RAG with Auto-Hop significantly outperforms** classical RAG — the graph traversal discovers dependencies that pure vector similarity misses.

### `corpus_rgpd/` — GDPR Regulatory Documents (3-4 PDFs)
Official French government documents on GDPR obligations for businesses and individuals, plus the EU AI Act legislative resolution.

**Why this corpus?** A homogeneous, well-structured regulatory corpus where **classical RAG already performs well**. This serves as a baseline to show that Graph-RAG doesn't degrade quality on simple corpora while adding value on complex ones.

### `analysis_samples/` — Documents for Corpus Analysis
Sample PDFs to test the "Analyze a document" feature (Step 4, 🔬 tab). Upload these against an existing corpus to see how the system identifies related chunks, assigns clusters, and generates analysis reports.

## Benchmarks

### `benchmarks/novatech/BENCHMARK.md`
Comparative benchmark on the NovaTech corpus: same questions answered with and without graph enrichment. Demonstrates Auto-Hop's ability to follow amendment chains and cross-references.

### `benchmarks/rgpd/BENCHMARK.md`
Comparative benchmark on the RGPD corpus: shows that Graph-RAG maintains quality on simpler corpora and adds marginal value through complementary relations.

## How to Reproduce

1. Create a new project in Word Weave Web
2. Upload all PDFs from a corpus directory
3. Run Clustering → Run Relations
4. Test the questions listed in the corresponding `BENCHMARK.md`
5. Compare your results with the documented benchmarks
