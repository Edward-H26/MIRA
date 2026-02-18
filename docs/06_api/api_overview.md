# MEMORIA API Introduction

This document provides the detailed API introduction for Section 6 of the assignment.

Related files:
- [URL routes](../../app/chat/urls.py)
- [API views](../../app/chat/api.py)
- [Service layer](../../app/chat/service.py)
- [Project README](../../README.md)

## 1. API Purpose

MEMORIA exposes read-oriented APIs so frontend pages and future external clients can access user memory and conversation data in structured JSON format.

Primary goals:
- support current UI features (for example, sidebar conversation search)
- provide filtered data retrieval via query parameters
- demonstrate both FBV and CBV implementation styles in Django

## 2. Base Route Group

All endpoints are under:
- `/chat/api/`

## 3. Authentication Scope

Most endpoints are user-scoped and protected by login checks.  
Responses only include data that belongs to the authenticated user.

## 4. Endpoint Overview

### 4.1 `GET /chat/api/memories/` (FBV)

Returns memory bullet records.

Supported filters:
- `q`: keyword search in memory content
- `type`: memory type filter
- `topic`: topic keyword filter
- `strength_min`: minimum strength threshold

Example:
- `/chat/api/memories/?q=python&type=1&strength_min=40`

### 4.2 `GET /chat/api/analytics/` (FBV)

Returns aggregated analytics summary for the authenticated user.

Payload includes:
- total memories/sessions/messages
- memory type distribution
- average strength
- helpful/harmful totals

### 4.3 `GET /chat/api/sessions/` (CBV)

Returns conversation session list.

Supported filter:
- `q`: title search

Example:
- `/chat/api/sessions/?q=project`

### 4.4 `GET /chat/api/sessions/<session_id>/messages/` (CBV)

Returns message list for a specific session.

Supported filter:
- `role`: role-based filter

Example:
- `/chat/api/sessions/12/messages/?role=2`

## 5. Response Design

Standard API endpoints return `JsonResponse` with list/count structures for easy frontend consumption.
