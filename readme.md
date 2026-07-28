# AI Coding Agent

An autonomous AI coding agent that explores an existing codebase, understands the project structure, plans an implementation, modifies the repository, verifies the changes, and generates a summary.

This project was developed as part of an AI Coding Agent assignment.

---

# Objective

Given a high-level product request such as:

> Improve the application so users can better organise and search their notes.

the agent automatically:

- Explores the repository
- Understands the project structure
- Identifies relevant files
- Creates an execution plan
- Implements the required changes
- Verifies the implementation
- Generates a summary of all modifications

No repository-specific logic is hardcoded, making the workflow reusable for similar Node.js projects.

---

# Architecture

```
                 User Task
                      │
                      ▼
             System Prompt
                      │
                      ▼
              Groq LLM (Llama)
                      │
          Function Calling API
                      │
      ┌───────────────┼────────────────┐
      │               │                │
      ▼               ▼                ▼
 list_dir()      read_file()     search_code()
      │               │                │
      └───────────────┼────────────────┘
                      │
                      ▼
               Planning Stage
                      │
                      ▼
              write_file()
                      │
                      ▼
             run_command()
                      │
                      ▼
           PLAN.md + CHANGES.md
```

---

# Agent Workflow

## 1. Repository Exploration

The agent begins by inspecting the repository.

It automatically:

- Lists project directories
- Reads important files
- Understands project structure
- Detects routes, controllers and models

Tools used:

- list_dir
- read_file
- search_code

---

## 2. Planning

Before modifying code, the agent creates a short implementation plan.

The plan contains:

- Features to implement
- Files to modify
- Assumptions
- Scope of work

The plan is:

- printed in the terminal
- saved as **PLAN.md**

---

## 3. Code Generation

The agent updates only the necessary project files.

Typical modifications include:

- Adding tags/categories
- Adding search functionality
- Updating routes
- Updating models
- Updating controllers

Existing functionality is preserved.

---

## 4. Verification

After modifications the agent performs verification using:

- JavaScript syntax checking
- Server startup (when permitted)
- API endpoint validation using curl

If verification cannot be completed because of sandbox restrictions, the limitation is reported.

---

## 5. Summary Generation

Finally the agent creates:

**CHANGES.md**

containing:

- Files modified
- Features added
- Verification results
- Assumptions
- Trade-offs

---

# Repository Exploration Strategy

Instead of assuming file names, the agent first explores the repository.

Typical workflow:

1. list_dir(".")
2. read_file(server.js)
3. read_file(routes)
4. read_file(controllers)
5. read_file(models)
6. search_code()

This allows the agent to understand the project before making modifications.

---

# Tools

The agent exposes five tools through function calling.

## list_dir

Lists project directories.

## read_file

Reads project files.

## search_code

Searches the repository using grep.

## write_file

Creates or updates project files.

## run_command

Executes safe verification commands inside the repository.

---

# Assumptions

- The repository is already cloned locally.
- The repository root is passed using `--repo`.
- The project already builds successfully.
- The requested feature should preserve existing functionality.
- The agent chooses a reasonable implementation when requirements are ambiguous.

---

# Trade-offs

- The agent prioritizes minimal code changes.
- Verification depends on sandbox permissions.
- Large files may be truncated before being sent to the LLM to reduce token usage.
- The implementation favors simplicity over adding new dependencies.

---

# Requirements

- Python 3.11+
- Groq API Key

Install dependencies

```bash
pip install -r requirements.txt
```

Set API key

Linux/macOS

```bash
export GROQ_API_KEY=your_api_key
```

Windows PowerShell

```powershell
$env:GROQ_API_KEY="your_api_key"
```

---

# Running the Agent

```bash
python agent.py \
--repo ../node-easy-notes-app \
--task "Improve the application so users can better organise and search their notes."
```

---

# Output Files

The agent automatically generates:

```
PLAN.md
CHANGES.md
AGENT_LOG.md
```

---

# Example Workflow

```
User Request
      │
      ▼
Explore Repository
      │
      ▼
Understand Codebase
      │
      ▼
Create Plan
      │
      ▼
Modify Code
      │
      ▼
Verify Changes
      │
      ▼
Generate Summary
```

---

# Future Improvements

- Support multiple programming languages
- Smarter repository exploration
- Semantic code search
- AST-based code editing
- Git diff generation
- Automatic rollback on verification failure
- Multi-file incremental editing
- Unit test generation
- Docker-based verification
- Support for multiple LLM providers

---

# Technologies Used

- Python 3.11+
- Groq API
- Llama 3
- Function Calling
- Node.js
- Express
- MongoDB

---

# Project Structure

```
ai-coding-agent/
│
├── agent.py
├── requirements.txt
├── README.md
├── .env.example
│
└── Generated Files
    ├── PLAN.md
    ├── CHANGES.md
    └── AGENT_LOG.md
```

---

# Author

Dhvani Kapatel

B.Tech Artificial Intelligence & Data Science
