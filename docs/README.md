# Kirana Technical Documentation

This folder contains technical documentation for Kirana's architecture, infrastructure, and implementation decisions.

Kirana is still an early-stage research prototype, so these docs should stay close to the code and record decisions as they become concrete. The goal is to make the retrieval design, infrastructure shape, evaluation assumptions, and setup requirements easy to inspect without overloading the project README.

## Current Documents

- [Setup](./setup.md): infrastructure setup, required credentials, and the resources created by `backend/setup.py`.
- [Ingestion Pipeline](./ingestion.md): receipt CLI flow, Splitwise import separation, storage responsibilities, observability, and error handling.
- [API Endpoints](./api.md): FastAPI Swagger/OpenAPI locations and the current chat API request/response contracts.
