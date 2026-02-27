# JSON Config Engine PoC

A Django-based Proof of Concept for a dynamic JSON configuration management system. This engine allows you to define strict configuration schemas (using JSON Schema paradigms) and apply targeted overrides for different organizations or tenants.

## Core Concepts

*   **Global Config Schema**: A system-wide singleton defining the structure, types, constraints, and default values of your configuration using a "namespaces" and "fields" dictionary.
*   **Organizations**: Tenant entities that can have specific configuration overrides applied to them.
*   **Effective Configuration**: The fully resolved configuration object resulting from merging an Organization's overrides on top of the active Global Config Schema's default values.
*   **Validation Rules**: Schemas can enforce strong typing, minimum/maximum values, allowed choices, mutability rules, and role/environment-based access policies.

## Project Architecture

The project is broken down into modular Django apps located in `apps/`:

*   `schema_registry`: Manages the creation, versioning, and validation of `ConfigSchema` and the active `GlobalConfigSchema`. Contains the robust `SchemaValidator`.
*   `organizations`: Manages tenant records (`Organization` model) and their specific JSON configuration overrides.
*   `config_core`: The execution engine. Contains the `ConfigResolver` (which merges defaults and overrides) and the `OverrideValidationService` (which ensures overrides don't violate schema rules).

## Setup Instructions

### Prerequisites
*   Python 3.12+
*   PostgreSQL
*   A created postgres database and user (e.g., `config_engine`)

### 1. Environment Setup
1. Clone the repository.
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # On Windows
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure your environment variables in a `.env` file at the project root:
   ```env
   DJANGO_SECRET_KEY="your-secret-key"
   DB_HOST="localhost"
   DB_PORT="5432"
   DB_NAME="config_engine"
   DB_USER="config_engine_user"
   DB_PASSWORD="your-password"
   ```

### 2. Database Initialization
Run the Django migrations to create the necessary tables:
```bash
python manage.py migrate
```

### 3. Create an Admin User
Create a superuser to access the Django admin panel and manage configurations via the GUI:
```bash
python manage.py createsuperuser
```

### 4. Running the Application
Start the development server:
```bash
python manage.py runserver
```
*   **API:** Access the API endpoints at `http://127.0.0.1:8000/api/v1/...`
*   **Admin Panel:** Access the GUI at `http://127.0.0.1:8000/admin/`

## Running Tests

The project includes a comprehensive `pytest` suite ensuring 100% coverage across core services and API views.

```bash
# Run all tests
pytest tests/test_config_engine.py -v

# Run tests with coverage report
pytest --cov=apps --cov-report=term-missing
```

## API Quickstart

Here is a brief workflow for using the REST API:

1.  **Define a Schema:** `POST /api/v1/schemas/` to define your application's configuration structure.
2.  **Register an Org:** `POST /api/v1/organizations/` to create a tenant (e.g., `name="Acme Corp"`). This returns an auto-assigned integer ID (e.g., `id=1`).
3.  **Apply Overrides:** `PUT /api/v1/organizations/1/config/` to apply specific values that differ from the schema defaults.
4.  **Fetch Effective Config:** `GET /api/v1/organizations/1/effective-config/` to retrieve the final, merged configuration dictionary for Acme Corp.
