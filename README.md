# Document Intelligence POC

**Compare agent harnesses on standard financial document analysis.**

This proof of concept evaluates how **Pi, Tau, and Codex** extract structured data, cite supporting evidence, and reconcile values across documents. Each harness receives the same task and assigned source files, works with its native tools, and returns JSON against a shared evaluation contract. Results and traces can be explored in **Phoenix**.

The current datasets focus on U.S. tax documents, including W-2, 1099, K-1, and Form 1040, with PDF, image, and JSON inputs.

## How it works

1. **Select a task.** Choose a dataset, harness, model, and reasoning effort.
2. **Read the source documents.** Each native invocation starts in a fresh Docker container with only its assigned inputs. Ground truth and evaluator code stay outside the worker.
3. **Return structured answers.** The harness produces field values and document, page, and field references.
4. **Score and compare.** Deterministic evaluators check schema, values, and evidence. Local reports and Phoenix capture scores, execution details, timing, and available token usage.

The runner does not pre-extract answers, repair responses, or use an LLM judge. A task passes only when execution succeeds and its schema, values, and evidence all satisfy the contract.

## Quick start

Run these commands from the repository root. You need **Docker with Compose**, **uv**, **Python 3.12–3.14** for the commands below, and an authenticated **Codex CLI session using a ChatGPT account**. Pi and Tau are installed inside the harness image. See the [setup guide](docs/OPERACION.md#preparar-el-entorno) for authentication and troubleshooting details.

### 1. Build the harness image and start Phoenix

```bash
docker build -f containers/harnesses.Dockerfile \
  -t doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0 containers
docker compose up -d --wait
```

### 2. Verify the dataset and environment

These checks verify dataset integrity, runtime configuration, and network connectivity without calling models.

```bash
uv run scripts/prepare_full_dataset.py --check

python3 -m evals --dataset datasets/tax-document-eval-v1 \
  --harness all --check --check-network
```

### 3. Run one document extraction task

```bash
./run.py --dataset datasets/tax-document-eval-v1 --harness codex \
  --model gpt-5.6-sol --thinking medium \
  --task extract_taxcalc_ty25_ca_001_w2_1 --timeout 300
```

This runs a real model invocation and publishes the results to [local Phoenix](http://127.0.0.1:6006). A local copy is saved under `runs/<id>/`.

## Compare harnesses

Run the same task with Pi, Tau, and Codex using the same model and reasoning effort:

```bash
./run.py --dataset datasets/tax-document-eval-v1 --harness all \
  --model gpt-5.6-sol --thinking medium \
  --task extract_taxcalc_ty25_ca_001_w2_1 --timeout 300
```

The three harnesses run sequentially and produce individual reports plus comparison JSON and CSV files. Use `--models MODEL_A MODEL_B` instead of `--model` to compare multiple models, or `--repetitions N` to repeat each task.

**Omitting `--task` runs every task in the selected dataset.** The full dataset requires 366 invocations per harness and model, per repetition. `--harness all` selects the three harnesses; it does not change the dataset.

## Datasets

| Dataset | Purpose | Scope |
|---|---|---|
| [Full evaluation set](datasets/tax-document-eval-v1/) | Prepared dataset for extraction and reconciliation | 319 documents · 55 cases · 366 tasks · 1,465 fields |
| [Mini POC](datasets/tax-mini-poc/README.md) | Small synthetic fixture for exploring the workflow | 5 PDFs · 1 case · 6 tasks · 54 fields |
| [Source collection](datasets/tax-document-dataset-v0.1/README.md) | Original source material and references used to prepare the full set | Reference material; not directly runnable |

The CLI defaults to the mini dataset. Pass `--dataset` explicitly to select the full set. The [dataset guide](docs/FULL_DATASET_READINESS.md) includes examples for PDF extraction, image reading, JSON inputs, and reconciliation across documents.

## Read the results

| Artifact | Contents |
|---|---|
| `runs/<id>/report.json` | Summary, exact inputs, raw answers, errors, scores, timing, usage, and harness metadata |
| `runs/<id>/scores.csv` | Scores for each task and repetition |
| `runs/<id>/dataset-snapshot.json` | Dataset prompts and expected answers for inspecting results |
| `runs/<id>/traces.json` | Spans recorded by the runner |
| [Phoenix](http://127.0.0.1:6006) | Published datasets, experiments, scores, and traces |

Start with `summary.tasks_passed` and `rows[].scores.task_pass` in `report.json`. **Exit code 0 does not mean every answer is correct**; individual scores determine whether a task passed.

`./run.py` evaluates and publishes results. `python3 -m evals` uses the same evaluation flow and saves reports locally without publishing evaluator results; native harness telemetry may still export spans. Publication retries and historical imports do not require new model calls—see the [operations guide](docs/OPERACION.md#recuperar-o-trasladar-resultados).

## Validation and scope

The [September 13, 2026 audit](docs/FULL_DATASET_AUDIT.md) records **256 passing tests** and **12/12 passing model runs** with `gpt-5.6-sol` at `medium` reasoning: four tasks across three harnesses, covering PDF, image, JSON, and reconciliation. The [saved artifacts](artifacts/2026-09-13/full-dataset/README.md) preserve the reports and supporting evidence.

These runs validate the sampled integrations and formats. The full 3,294-invocation matrix across three models and three harnesses has not been run. The full dataset is a development set, and these checks do not establish a harness ranking.

Evaluation covers selected observable fields and explicitly defined sums. It does not assess complete tax returns or general tax reasoning. Historical results retain their original dataset, prompt, and scoring identities; see [comparison compatibility](docs/FINGERPRINTS.md) before combining or importing runs.

## Repository map

| Path | Responsibility |
|---|---|
| [`run.py`](run.py) | Evaluation and Phoenix publication entry point |
| [`evals/`](evals/) | Task loading, prompts, adapters, scoring, reporting, and telemetry |
| [`harnesses/`](harnesses/) | Native harness profiles and configuration examples |
| [`containers/`](containers/) | Harness image, worker process, and egress proxy |
| [`datasets/`](datasets/) | Source documents, tasks, and evaluation references |
| [`preparation/`](preparation/) / [`scripts/`](scripts/) | Dataset preparation, integrity checks, and command entry points |
| [`tests/`](tests/) | Unit, dataset, and Docker/Phoenix integration tests |
| `runs/` / [`artifacts/`](artifacts/) | Local results ignored by Git / versioned evidence and run archives |
| [`docs/`](docs/README.md) | Guides, design decisions, and audits |

## Further reading

The detailed guides are currently in Spanish.

| Guide | What you will find |
|---|---|
| [Project walkthrough](docs/GUIA_DEL_PROYECTO.md) | Architecture, glossary, a complete task walkthrough, and where to make changes |
| [Operations](docs/OPERACION.md) | Environment setup, score interpretation, troubleshooting, recovery, and tests |
| [Full dataset guide](docs/FULL_DATASET_READINESS.md) | Source verification and execution examples |
| [Documentation index](docs/README.md) | Design decisions, audits, and historical evidence |

## License

The project’s original code is licensed under the [MIT License](LICENSE). Third-party components and datasets may carry separate licenses; their own notices apply.
