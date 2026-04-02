# Maestro-Flow: Dynamic Admissions Engine

A configuration-driven workflow orchestrator built with **FastAPI** and **Pydantic**. Designed to handle complex, multi-step user journeys with flexible routing and automated status resolutions.

## System Architecture

The project is structured to enforce a strict separation of concerns, ensuring scalability and maintainability. Here is the complete breakdown of the system files and directories:

### Application Core (`app/`)
| File / Directory | Description |
| :--- | :--- |
| `app/main.py` | FastAPI application entry point, global configurations, and exception handling. |
| `app/api/endpoints.py` | REST API routes handling HTTP requests (`/users`, `/flow`, `/tasks/complete`, etc.). |
| `app/api/schemas.py` | Pydantic models strictly for API request/response validation. |
| `app/core/conditions.py` | Logic factories for dynamic routing conditions (e.g., score thresholds, max attempts). |
| `app/core/engine.py` | `WorkflowEngine`: The stateless, generic orchestrator that evaluates and routes users. |
| `app/core/flow_config.py` | The static definition of the entire admissions flow graph (`FLOW_STEPS`, `FLOW_TASKS`). |
| `app/core/store.py` | In-memory state management (`UserStore`), ready to be swapped for a persistent DB. |
| `app/core/validators.py` | Pure functions providing strict runtime payload validation before routing. |
| `app/models/schemas.py` | Internal system models (`TaskNode`, `StepNode`, `UserState`, `Outcome`). |

### Test Suite (`tests/`)
| File / Directory | Description |
| :--- | :--- |
| `tests/test_api.py` | Unit tests for FastAPI endpoints, request parsing, and response serialization. |
| `tests/test_conditions.py` | Boundary and logic testing for all condition factories. |
| `tests/test_engine.py` | Isolated unit tests for the engine's routing logic using minimal synthetic graphs. |
| `tests/test_integration_api.py` | Full End-to-End tests driving the HTTP layer through happy and rejection paths. |
| `tests/test_masterschool_flow.py` | Integration tests verifying the exact business logic of the Masterschool graph. |
| `tests/test_store.py` | Unit tests for the data access layer ensuring accurate state persistence. |
| `tests/test_validators.py` | Exhaustive testing ensuring bad payloads are rejected instantly. |

### Infrastructure & Configuration
| File / Directory | Description |
| :--- | :--- |
| `Dockerfile` | Containerization configuration for a zero-setup production deployment. |
| `.dockerignore` | Prevents unnecessary files (like tests and cache) from bloating the container. |
| `requirements.txt` | Production and testing dependencies with strict version pinning. |

### The "Creative PM" Solution: Engine vs. Configuration
The core design philosophy of Maestro-Flow is the strict separation between the **Engine** and the **Business Logic**. 
* The **`WorkflowEngine`** is completely blind to the domain. It has zero hardcoded knowledge of what an "IQ Test" or "Interview" is. It simply evaluates conditions and moves users between abstract nodes.
* The **Rules** are completely externalized into `app/core/flow_config.py`. 

This architecture guarantees that when Product Managers inevitably request changes to the funnel, the system adapts instantly without requiring a single line of code change in the engine itself.

##  Modifying the Flow

All flow modifications are centralized in `app/core/flow_config.py`. 

* **Changing the Entry Point:** If you change the very first task or step of the funnel, ensure you update the `STARTING_STEP_ID` and `STARTING_TASK_ID` constants at the top of the file.
* **Step Transitions (Fallthrough):** If a task's completion should advance the user to the *next step*, leave the routing target (`next_task_id`) as `None` in the task's `Outcome`. The engine will naturally fall through to the Step's `next_steps` routing layer.

## How to Run the Project

### Option 1: Docker (Recommended)
The application is fully containerized for a zero-setup experience.

1. Build the image:
   ~~~bash
   docker build -t maestro-flow-app .
   ~~~
2. Run the container:
   ~~~bash
   docker run -p 8000:8000 maestro-flow-app
   ~~~
*Once running, access the interactive API documentation at: [http://localhost:8000/docs](http://localhost:8000/docs)*

### Option 2: Run Locally
Ensure you have Python 3.10+ installed.

1. Install dependencies:
   ~~~bash
   pip install -r requirements.txt
   ~~~
2. Start the server:
   ~~~bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ~~~

## API Endpoints

The system fulfills all delivery requirements via the following REST endpoints:
* `POST /users` - Create a new user and get a unique ID.
* `GET /flow` - Retrieve the entire static flow configuration (enabling the frontend to display progress).
* `GET /users/{user_id}/current` - Fetch the user's current step and task.
* `PUT /tasks/complete` - Submit task payload. The engine validates the data and routes the user automatically.
* `GET /users/{user_id}/status` - Check if the user is `in_progress`, `accepted`, or `rejected`.

## Testing

The system is protected by **270 automated tests** achieving **95% code coverage**. This includes Unit Tests, Engine-routing tests on synthetic isolated graphs, and full End-to-End integration tests covering both the happy path and all rejection paths.

To run tests locally with a coverage report:
   ~~~bash
   python -m pytest --cov=app
   ~~~