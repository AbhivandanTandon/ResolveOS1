ResolveOS AI ML export
- resolveos_kb.pkl: RAG knowledge base (load with resolveos_retriever.KnowledgeBase)
- cases.parquet / hard_set.parquet: synthetic datasets
- *.joblib: trained models (triage, action, risk)
- real_labeled.parquet / real_labels_review.csv: real Banking77 + CFPB text with Nemotron-made labels (spot-check them)
- metrics.json: results, including retrieval diagnostics. Simulator labels are synthetic; real-text labels are model-made. Neither is production ground truth.
- Retrieval: hybrid BGE + lexical RRF. Operational search excludes Wikipedia, raw customer messages and unverified external pages by default; background sources require explicit opt-in.
- Triage: TF-IDF and BGE-logistic models select regularization using validation macro-F1 and use class weighting.
- Data sources: Banking77 (PolyAI, CC BY 4.0 per its dataset card), CFPB Consumer Complaint Database (public), Wikipedia (CC BY-SA, attribute if you publish). Confirm licences before redistributing.
Only load .pkl/.joblib files you created yourself.
