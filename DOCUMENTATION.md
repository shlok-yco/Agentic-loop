# Agentic-loop Technical Documentation

Welcome to the technical documentation for the Agentic-loop repository. This document is designed for developers, data engineers, and tech leads who want to understand, extend, or maintain the multi-agent analytical pipeline.

---

## 1. System Overview

**Agentic-loop** is an automated, multi-agent data analysis and visualization pipeline. It orchestrates a workflow that accepts tabular data (like CSVs), profiles and cleans the data, determines key business objectives, generates insightful analytical summaries, and ultimately produces interactive visualizations.

### Core Capabilities
- **Automated Data Ingestion & Profiling**: Safely reads uploaded CSV files, evaluates column types, missing values, and anomalies.
- **Data Preparation**: Cleans data and generates a pre-processed dataset for analysis.
- **Autonomous Analytics**: A team of AI sub-agents collaboratively define business objectives and extract key insights.
- **Dynamic Visualization**: Generates configuration files (ECharts) to render dynamic, interactive charts based on the generated insights.
- **Stateful Execution**: Runs asynchronously with continuous state tracking, allowing a frontend to poll the run status and download results.

---

## 2. Technology Stack

- **Backend Framework**: [FastAPI](https://fastapi.tiangolo.com/) for high-performance API endpoints and background task management.
- **AI / LLM Orchestration**: [LangGraph](https://langchain-ai.github.io/langgraph/) and [LangChain](https://python.langchain.com/) for structuring the state machine and agent communication.
- **Data Processing**: [Pandas](https://pandas.pydata.org/) for robust data manipulation.
- **Frontend**: [React](https://react.dev/) + [Vite](https://vitejs.dev/) with [Tailwind CSS](https://tailwindcss.com/) for a snappy, modern user interface.
- **Visualization**: [Apache ECharts](https://echarts.apache.org/) (configured via JSON payloads from the backend).

---

## 3. Architecture Deep Dive

The system is split into a REST API (FastAPI) acting as the frontend interface and a LangGraph-powered state machine running the autonomous pipeline in the background.

### FastAPI API Layer (`main.py`)
The entry point of the backend application. Key responsibilities include:
- `POST /upload`: Accepts CSV files, copies them into a temporary local directory, and returns the path.
- `POST /run`: Initiates the data pipeline in the background. It provisions a unique `workspace/<run_id>` directory, prepares the initial state, and invokes the LangGraph workflow (`app_graph.ainvoke`).
- `GET /status/{run_id}`: Polls the current state of a pipeline run. Useful for the frontend to show a live progress bar or loading spinner.
- `GET /result/{run_id}`: Fetches the final output of the pipeline (insights, chart options) once the status reaches `COMPLETED`. It attempts to reconstruct state from disk if memory is dropped.

### LangGraph Supervisor (`src/graph/supervisor.py`)
The Supervisor node acts as the "Tech Lead." It manages the global state (`SupervisorState`) and decides which sub-agent to invoke based on missing artifacts.
- **State Machine Progression**: Evaluates the `output_artifacts` dictionary. For example, if `data_profile` is missing, it assigns tasks to the `lead_engineer`.
- **Delegation**: Calls sub-agents (`lead_data_engineer`, `lead_analyst`) as LangChain tools, passing them the required inputs and expected output formats.

### Sub-Agents
Agents reside in `src/agents/` and consist of specialized LangGraph workflows.

1. **Lead Data Engineer (`src/agents/engineering/lead_engineer.py`)**
   - **Goal**: Perform physical data processing.
   - **Tools**: Executes Python code (e.g., pandas operations) to inspect and clean the dataset.
   - **Outputs**: `data_profile.json`, `clean_dataset.csv`.

2. **Lead Data Analyst (`src/agents/analytics/lead_analyst.py`)**
   - **Goal**: Find meaning in the data and design visualizations.
   - **Tools**: Defines business metrics, executes aggregations, and structures JSON configurations.
   - **Outputs**: `business_objectives.json`, `approved_insights.json`, `approved_visualizations.json`.

---

## 4. State & Artifact Management

Agentic-loop heavily relies on a disk-backed workspace strategy to prevent LLM context windows from overflowing. 

### Workspace Structure
Whenever `/run` is called, a folder is created at `workspace/<run_id>/`:
- `input/`: Stores the raw uploaded dataset.
- `output/`: Stores the serialized output of the pipeline (JSON profiles, CSV files).
- `scripts/`: Stores intermediate Python scripts executed by the engineering agent.
- `live_logs.json`: An append-only log file capturing the thought process and actions of the agents for real-time frontend consumption.

### Artifact-Driven Workflow
The supervisor uses an artifact existence map (`ARTIFACT_STEP_MAP`) to move the pipeline forward:
1. **init** -> **data_preparation** (waits for `data_profile` and `clean_dataset`).
2. **data_preparation** -> **analytics_and_visualization** (waits for `business_objectives`).
3. **analytics_and_visualization** -> **visualization_completed** (waits for `approved_visualizations`).

State variables are truncated before being passed to the Supervisor prompt to minimize Token Time To First Byte (TTFT) and avoid context limits.

---

## 5. Agent Interactions & Prompts

Prompts form the "brain" of each agent, enforcing standard operating procedures (SOPs).
- **Location**: `src/prompts/`
- **Supervisor Prompt**: Instructs the model to act as a strict manager. It cannot run code itself; it must delegate to its tools (`lead_data_engineer`, `lead_analyst`).
- **Sub-agent Prompts**: Extremely rigid. They are explicitly told *what tools they have* and *how to report back*. For example, the `dataanalyst_prompt.py` specifically enforces the generation of ECharts options using template strings (e.g., `{@dimension}`) instead of raw JavaScript functions.

---

## 6. Frontend Integration

The frontend (located in `frontend/`) interacts with the backend using the following flow:
1. **Upload**: User uploads a file. The UI calls `/upload` and receives a file path.
2. **Run**: The UI calls `/run` with the user's query and the file path. It receives a `run_id`.
3. **Polling**: The UI loops a call to `/status/{run_id}` every few seconds, displaying the `live_logs.json` to the user as a real-time terminal feed.
4. **Rendering**: Once status is `COMPLETED`, the UI calls `/result/{run_id}`.
   - The backend serves `approved_insights.json` and parses `approved_visualizations.json`.
   - The React frontend uses an ECharts wrapper to dynamically mount the visualizations within a dashboard layout.

---

## 7. Local Setup & Development Guide

### Prerequisites
- Python 3.9+
- Node.js 18+

### Backend Setup
1. Navigate to the root directory.
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure your `.env` file (ensure your LLM API keys, like OpenAI or Google GenAI, are set).
5. Start the FastAPI server:
   ```bash
   python main.py
   ```
   *The server typically runs on `http://localhost:8000`.*

### Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the Vite dev server:
   ```bash
   npm run dev
   ```

### Debugging the Pipeline
If an agent gets stuck or throws an error:
- Check the `workspace/<run_id>/live_logs.json` to see the agent's last thought.
- Examine `logs/supervisor.log` and `logs/lead_engineer.log` for Python-level exceptions.
- You can manually inject a state snapshot using LangGraph's checkpointer to test a specific step without re-running the entire pipeline.
