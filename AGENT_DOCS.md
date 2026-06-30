# Agent Implementation Documentation

This document provides a deep dive into the architecture, state management, tools, and guardrails of the AI agents within the `Agentic-loop` pipeline. The system utilizes a hierarchical Supervisor-Worker pattern implemented using LangGraph.

---

## 1. Agentic Architecture Overview

The multi-agent system orchestrates complex data engineering and analytical workflows through a centralized supervisor delegating to specialized sub-agents. 

- **State Management**: Every node operates on a strictly typed dictionary (`TypedDict`). Global state is managed by the supervisor, while each sub-agent maintains its own isolated context during task execution.
- **Guardrails**: To prevent hallucinations and infinitely looping state transitions, the system enforces strict schema returns, validates JSON structures before disk writes, and truncates overly large artifacts from LLM context to avoid `context_length_exceeded` errors.
- **Disk-Backed Memory**: Sub-agents write major artifacts directly to the workspace directory. The Supervisor relies on these disk writes (via `ARTIFACT_STEP_MAP`) rather than holding massive dataframes in memory.

---

## 2. The Supervisor Node

The Supervisor (`src/graph/supervisor.py`) acts as the project manager. It does not execute data processing or analysis directly; it decides *who* to call next based on the presence of physical artifacts on the disk.

### `SupervisorState`
The global state tracks the overall project progression:
- `messages`: A list of conversation messages.
- `current_step`: Tracks progression (`init`, `data_preparation`, `analytics_and_visualization`, `visualization_completed`).
- `pending_tasks`, `completed_tasks`, `failed_tasks`: Task progression queues.
- `input_artifacts` & `output_artifacts`: Maps showing the location of raw and generated datasets.
- `<artifact_keys>` (e.g., `data_profile`, `approved_insights`): Cached references to the contents of generated files.

### Step Progression (`ARTIFACT_STEP_MAP`)
The Supervisor automatically deduces its current step by looking at the workspace output directory.
- For example, if `data_profile.json` and `clean_dataset.csv` exist, the supervisor knows `data_preparation` is complete and advances to `analytics_and_visualization`.

### `update_project_state`
This is a critical LangGraph node that fires after any tool (sub-agent) returns data to the supervisor. It acts as the ultimate authority on state mutations.
1. **Payload Parsing**: Extracts the JSON returned by the sub-agents and handles double-encoding resilience.
2. **Task Syncing**: Merges the `completed_tasks` returned by the sub-agent into the global `completed_tasks` dictionary and removes them from `pending_tasks`.
3. **Artifact Syncing**: Verifies that generated artifacts actually exist on disk.
4. **Step Advancement**: Reads the disk to evaluate the highest achieved step using the `ARTIFACT_STEP_MAP` and updates `current_step` accordingly.

### Supervisor Guardrails
- **Context Truncation**: Artifacts larger than 2000 characters are intelligently truncated (`_truncate_dict`) before being passed to the Supervisor prompt.
- **Message Limit**: Only the first system message and the last 15 messages are kept in context to prevent token overflow.

---

## 3. Lead Data Engineer

The Engineering agent (`src/agents/engineering/lead_engineer.py`) is tasked with physical data transformations, profiling, and executing Python code.

### `LdeState` (Sub-agent State)
Tracks local execution: `task_summary`, `tasks`, `pending_tasks`, `completed_tasks`, `failed_tasks`, `generated_artifacts`, and `report_submitted`.

### `update_state`
This node runs after the engineer uses a tool.
1. Parses JSON responses from engineering tools.
2. Appends generated files to `generated_artifacts`.
3. Updates `completed_tasks` or `failed_tasks` based on the validation status returned by the tool.
4. Detects when the `submit_engineer_report` tool is called and flags `report_submitted = True` to terminate the sub-agent graph.

### Engineering Tools (`src/agents/engineering/tools.py`)

1. **`analyze_and_profile_dataset`**
   - **Role**: Automatically reads the CSV, generates a complete statistical profile, and extracts summary rows.
   - **Guardrail**: Uses custom robust pandas typing to prevent serialization errors.

2. **`clean_dataset`**
   - **Role**: Performs normalization, deduplication, and handles null fills via a pre-defined strategy.
   - **Guardrail**: Coerces column names and forces structural schema changes dynamically based on the input JSON parameters.

3. **`generate_python_script`**
   - **Role**: Prompts the LLM via `SCRIPT_GENERATOR_PROMPT` to output raw pandas code for custom data transformations not covered by `clean_dataset`.
   - **Guardrail**: Strips markdown formatting automatically and forces a Python namespace return.

4. **`execute_python_script`**
   - **Role**: Executes the python script directly using an in-process `exec()`.
   - **Guardrail**: Overrides `json.dumps` internally with an `NpEncoder` to ensure Numpy values (e.g., `np.int64`) are seamlessly converted to valid JSON primitives, preventing pipeline crashes on script outputs. Captures `stdout` and `stderr`.

5. **`validate_schema`**
   - **Role**: Validates that required columns exist and checks for forbidden nulls.

6. **`verify_artifact`** & **`read_artifacts`**
   - **Role**: Utility tools to quickly inspect outputs or confirm successful disk writes.

7. **`submit_engineer_report`**
   - **Role**: Hand-off mechanism mapping execution summary back to the Supervisor.

---

## 4. Lead Data Analyst

The Analyst agent (`src/agents/analytics/lead_analyst.py`) focuses on generating business intelligence and rendering visualizations. 

### `update_state` (Analyst)
Similar to the engineering agent, this parses responses from analyst tools and handles the sub-agent state transitions.

### Analytics Tools (`src/agents/analytics/tools.py`)

1. **`read_dataset_sample`**
   - **Role**: Reads the first N rows and basic metadata. Prevents the Analyst from reading massive datasets entirely into LLM memory.

2. **`compute_statistics`**
   - **Role**: Robust tool for running complex pandas `.groupby().agg()` operations and `.corr()` matrices dynamically.
   - **Guardrail**: Caps aggregation outputs to 100 rows to safeguard the LLM context limit.

3. **`generate_echarts_option`**
   - **Role**: Accepts JSON configuration payloads meant for Apache ECharts and writes them to `approved_visualizations.json`.
   - **Guardrail (Critical)**: Scans the JSON payload for strings like `[object Object]`, `toLocaleString`, and `function(`. Javascript functions are prohibited in the backend JSON payload because they cannot be cleanly serialized to the frontend. The tool returns a strict error enforcing the use of ECharts formatter strings (e.g., `{@dimension}`).

4. **`read_artifact`** & **`write_artifact`**
   - **Role**: Used to save insights and preprocessing blueprints.
   - **Guardrail**: Truncates any read artifact exceeding 15,000 characters. Re-validates written artifacts for JSON integrity.

5. **`submit_analyst_report`**
   - **Role**: Handoff mechanism back to the Supervisor.

---

## 5. Prompting Strategy

The standard operating procedures (SOPs) are defined strictly within `src/prompts/`.
- **Systematic Enforcement**: Agents are given highly explicit step-by-step instructions. For example, the `dataanalyst_prompt.py` lists the exact keys needed for the `approved_insights` structure.
- **Tool-First Behavior**: Agents are prompted to leverage tools rather than attempting to guess or hallucinate answers. The Data Engineer prompt explicitly commands the agent to generate scripts for any logic it cannot confidently accomplish via default functions.
- **Data Encapsulation**: The LLM relies primarily on metadata summaries and dataset profiles to make decisions, rather than directly reading raw CSV data, which ensures massive performance gains and stability.
