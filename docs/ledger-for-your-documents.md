# Ledger for your documents

**Cited answers over your contracts, policies or reports, with an accuracy report on your own
questions.**

## What you get

- Ask a question in plain English; every sentence of the answer links to the paragraph it came
  from, so anyone can check it in one click.
- Every number is recomputed before it is shown. If the arithmetic does not hold, the answer is
  corrected or flagged, never silently wrong.
- When your documents do not answer the question, Ledger says so and shows the closest passages.
- An **accuracy report on your own questions**: we write 50–100 questions with you, measure how
  often Ledger is right, and show you where it fails before you rely on it.

## How it works

1. Put your PDFs, Word-exported HTML or text files in one folder.
2. Describe the folder in a short YAML file (name, where it is, optional year in file names).
3. `ledger ingest --folder your_docs.yaml` indexes it on your own machine.
4. Ask through the web page or the API.

Private documents stay private: run the model locally with Ollama, or on a paid API tier with
no data retention. Nothing needs to leave your network.

## Good fits

Policy and procedure libraries, contract repositories, board packs and annual reports, technical
manuals, grant and tender documents.
