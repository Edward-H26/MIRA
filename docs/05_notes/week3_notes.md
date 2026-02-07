# MEMORIA Week 3 Progress Notes

These notes document the MEMORIA project's weekly progress for Feb 1 through Feb 6, 2026. They cover the project structure, security practices, GitHub workflow, views, templates, view-model-URL-template connection maps, challenges encountered, and future plans.

---

## Section 1: Structure, Security, and GitHub Workflow

### 1.1 Split Settings Pattern

The project uses a split settings pattern under `memoria/settings/` with four files:

| File | Purpose |
|---|---|
| `__init__.py` | Package marker (empty); lets Django import `memoria.settings` as a module |
| `base.py` | Shared settings for every environment: `INSTALLED_APPS`, `MIDDLEWARE`, `TEMPLATES`, `DATABASES`, `AUTH_PASSWORD_VALIDATORS`, static/media paths, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL` |
| `development.py` | Dev overrides: imports everything from `base`, sets `DEBUG`, `ALLOWED_HOSTS` for localhost |
| `production.py` | Prod overrides: imports everything from `base`, sets `DEBUG`, `ALLOWED_HOSTS` for the deployment domain |

The active settings module is selected via `DJANGO_SETTINGS_MODULE` in `manage.py` and `wsgi.py`/`asgi.py`.

### 1.2 Environment Variables

- **`.env`** stores the `DJANGO_SECRET_KEY`. The project uses `django-environ` to read it in `base.py` so the key never appears in version-controlled code.
- **`.env.example`** provides a template: `DJANGO_SECRET_KEY="YOUR_KEY"`. Contributors clone the repo, copy `.env.example` to `.env`, and fill in their own key.

### 1.3 .gitignore Coverage

The `.gitignore` excludes:

- Python bytecode (`__pycache__/`, `*.pyc`)
- Virtual environments (`venv/`, `.venv/`)
- IDE configs (`.idea/`, `.vscode/`)
- Django logs and database files
- The `.env` file itself (secrets never committed)
- Collected static files (`staticfiles/`)
- Media uploads (`media/`)
- macOS artifacts (`.DS_Store`)

### 1.4 Branching Strategy

The repository maintains six branches:

| Branch | Role |
|---|---|
| `main` | Stable production-ready code |
| `dev` | Integration branch; features merge here first |
| `feature/a` | Feature development (data models, views, services) |
| `feature/b` | Feature development (secondary features) |
| `feature/template` | Template and UI development |
| `release` | Release candidate staging |

Contributors work on `feature/*` branches, merge into `dev` for integration testing, then promote to `release` and finally `main`.

### 1.5 README.md and Docs Directory

The `README.md` at the project root describes the project name (MEMORIA), team (MIRA, Team 4), tech stack, and setup instructions. The `docs/` directory is organized as:

```
docs/
  01_project_documents/    # Idea description PDF, team contribution report
  02_wireframes/           # UI wireframes v1, v2, v3 iterations (PNG) + final PDF
  03_data_model/           # ER diagrams (Mermaid source, PNG, SVG)
  04_branching_strategy/   # Git branching documentation
  05_notes/                # Weekly notes (this file)
  design_choice/           # database_design_choice.md (naming, constraints, indexes)
```

---

## Section 2: Views

### 2.1 View Type Summary

| View Type | Views That Fulfill It |
|---|---|
| **HttpResponse FBV** (function-based view returning `HttpResponse` directly via `loader.get_template`) | `home()`, `landing()` |
| **render() FBV** (function-based view using `render()` shortcut) | `login_view()`, `register_view()`, `logout_view()`, `profile_view()`, `change_password_view()`, `chat_view()`, `memory_view()` |
| **Base CBV** (class-based view subclassing `django.views.View`) | `ConversationMessagesView` |
| **Generic CBV** (class-based view subclassing `django.views.generic.DetailView`) | `MemoryBulletsView` |

### 2.2 View Details

**`home(request)`** in `app/memoria/views.py`
Uses `loader.get_template("memoria/home.html")` and returns `HttpResponse(template.render(context, request))`. On GET it displays the dashboard with the user's sessions and memories. On POST it creates a new `Session`, adds the first `Message` pair (user + agent), and redirects to the conversation URL.

**`landing(request)`** in `app/memoria/views.py`
Uses `loader.get_template("memoria/landing.html")` and returns `HttpResponse(template.render({}, request))`. Renders the marketing landing page for unauthenticated visitors.

**`not_found_view(request, exception)`** in `app/memoria/views.py`
Custom 404 handler. Redirects to `memoria:home`.

**`login_view(request)`** in `app/users/views.py`
Render FBV decorated with `@require_http_methods(["GET", "POST"])`. GET returns the login form (supports AJAX partial rendering). POST authenticates via `services.authenticate_and_login()` and redirects.

**`register_view(request)`** in `app/users/views.py`
Render FBV decorated with `@require_http_methods(["GET", "POST"])`. GET returns the registration form. POST calls `services.register_and_login()` to create both `auth.User` and the `User` profile, then logs in.

**`logout_view(request)`** in `app/users/views.py`
Render FBV decorated with `@require_http_methods(["GET", "POST"])`. POST calls `django.contrib.auth.logout()` and redirects.

**`profile_view(request)`** in `app/users/views.py`
Render FBV decorated with `@login_required` and `@require_http_methods`. GET shows the profile page. POST handles email updates and profile image uploads.

**`change_password_view(request)`** in `app/users/views.py`
Render FBV decorated with `@login_required` and `@require_http_methods`. GET returns the password change form (AJAX). POST validates old password, checks new password confirmation, updates, and calls `update_session_auth_hash()` so the session stays active.

**`chat_view(request)`** in `app/chat/views.py`
Simple render FBV. Returns `render(request, "chat/chat.html")`.

**`memory_view(request)`** in `app/chat/views.py`
Render FBV decorated with `@login_required`. Retrieves the user's `MemoryBullet` objects with `select_related("memory")`. Supports query parameters: `q` (text search via `icontains`), `type` (filter by `MemoryType`), `sort` (order by `created_at`, `strength`, or computed `affect = helpful_count - harmful_count`). Uses Django's `ExpressionWrapper` and `F()` expressions for the affect annotation.

**`ConversationMessagesView`** in `app/chat/views.py`
Base CBV subclassing `django.views.View`, decorated with `@method_decorator(login_required)`. GET prefetches messages ordered by `created_at` and renders `conversation_detail.html`. POST accepts a new message, calls `create_user_message_with_agent_reply()`, and supports both standard redirect and AJAX (`JsonResponse`) responses.

**`MemoryBulletsView`** in `app/chat/views.py`
Generic CBV subclassing `django.views.generic.DetailView`. Sets `model = Memory`, `template_name = "chat/memory_detail.html"`, `pk_url_kwarg = "memory_id"`. Overrides `get_queryset()` to filter by the authenticated user's profile and prefetch related `memorybullet_set`.

---

## Section 3: Templates

### 3.1 Base Template and Block Tags

The base template lives at `templates/base.html` (261 lines). It defines the full page shell: sidebar with collapsible navigation, top navbar with avatar dropdown menu, and a main content area.

Block tags defined in `base.html`:

| Block Tag | Purpose |
|---|---|
| `{% block title %}` | Page title (defaults to "Dashboard") |
| `{% block extra_css %}` | Additional stylesheet links |
| `{% block body %}` | Entire page body (rarely overridden directly) |
| `{% block conversations %}` | Sidebar conversation list; uses `{% for session in sessions %}` with `{% empty %}` |
| `{% block sidebar_content %}` | Extra sidebar content below the conversation list |
| `{% block content %}` | Main content area (most commonly overridden by child templates) |
| `{% block extra_js %}` | Additional script tags |

### 3.2 Template Inheritance

All app-level templates extend the base:

- `app/memoria/templates/memoria/home.html` extends `base.html`, overrides `{% block content %}` with the dashboard message input form.
- `app/chat/templates/chat/conversation_detail.html` extends `base.html`, overrides `{% block title %}`, `{% block extra_css %}`, and `{% block content %}`.
- `app/chat/templates/chat/memory.html` extends `base.html`, overrides `{% block title %}`, `{% block extra_css %}`, and `{% block content %}`.
- `app/users/templates/users/profile.html` extends `base.html`, overrides content blocks for profile management.

The `memoria/templates/memoria/landing.html` does **not** extend `base.html`; it is a standalone page with its own full HTML structure, separate stylesheets, and login/register modals.

### 3.3 Loops with Empty States

Three templates demonstrate `{% for %}...{% empty %}` patterns:

1. **`base.html`** (sidebar conversations):
   ```
   {% for session in sessions %}
     <a href="{{ session.get_absolute_url }}">{{ session.title|default:"Untitled" }}</a>
   {% empty %}
     <div class="conversation-empty">No conversation history</div>
   {% endfor %}
   ```

2. **`conversation_detail.html`** (messages):
   ```
   {% for message in session.messages.all %}
     ...message bubble...
   {% empty %}
     <div class="conversation-empty-state">No messages yet.</div>
   {% endfor %}
   ```

3. **`memory.html`** (memory bullets):
   ```
   {% for bullet in bullets %}
     ...memory card...
   {% empty %}
     <div class="memory-empty">No memory bullets yet.</div>
   {% endfor %}
   ```

### 3.4 Template Reuse Patterns

- **Partial rendering for AJAX**: `login_form.html`, `register_form.html`, and `password_change_form.html` are rendered as partials (without extending `base.html`) when requested via AJAX (`X-Requested-With: XMLHttpRequest`). This allows them to be loaded inside modals on the landing page.
- **Custom template tags**: The `chat_extras` templatetag library provides a `relative_time` filter used across conversation listings to display "X ago" for recent timestamps.
- **Context processors**: `app/chat/context_processors.user_sessions` injects the authenticated user's session list into every template context, enabling the sidebar conversation list in `base.html` without each view passing sessions explicitly.

---

## View-Model-URL-Template Connection Map

### Unit 1: Landing Page

| Layer | Detail |
|---|---|
| **View** | `landing()` FBV in `app/memoria/views.py` |
| **Model(s)** | None |
| **URL** | `path("", views.landing, name="landing")` in `app/memoria/urls.py` |
| **Template** | `memoria/templates/memoria/landing.html` |
| **Connection** | The root URL `""` in the `memoria` namespace routes to `landing()`. The view loads the template via `loader.get_template()` and returns `HttpResponse`. No model data is needed because this is a static marketing page with login/register modals. |

### Unit 2: Home / Dashboard

| Layer | Detail |
|---|---|
| **View** | `home()` FBV in `app/memoria/views.py` |
| **Model(s)** | `Session`, `Memory`, `Message`, `User` (profile) |
| **URL** | `path("home/", views.home, name="home")` in `app/memoria/urls.py` |
| **Template** | `app/memoria/templates/memoria/home.html` |
| **Connection** | On GET, `home()` queries `Session.objects.filter(user=profile)` and `Memory.objects.filter(user=profile)`, passes them as context, and returns `HttpResponse(template.render(context))`. On POST, it creates a new `Session` and two `Message` objects (user + agent), then redirects to the session's `get_absolute_url()`. The template extends `base.html` and displays a message input form. |

### Unit 3: Conversation Detail

| Layer | Detail |
|---|---|
| **View** | `ConversationMessagesView` (Base CBV) in `app/chat/views.py` |
| **Model(s)** | `Session`, `Message`, `User` (profile) |
| **URL** | `path("c/<int:session_id>/", views.ConversationMessagesView.as_view(), name="conversation_detail")` in `app/chat/urls.py` |
| **Template** | `app/chat/templates/chat/conversation_detail.html` |
| **Connection** | The URL captures `session_id`. GET prefetches related messages ordered by `created_at`, filters sessions by the authenticated user's profile, and renders the conversation. POST calls `create_user_message_with_agent_reply()` service to add a new message pair, then either redirects or returns `JsonResponse` for AJAX. The template loops through `session.messages.all` with an `{% empty %}` fallback. |

### Unit 4: Memory Management

| Layer | Detail |
|---|---|
| **View** | `memory_view()` FBV in `app/chat/views.py` |
| **Model(s)** | `MemoryBullet`, `Memory`, `User` (profile) |
| **URL** | `path("memory/", views.memory_view, name="memory")` in `app/chat/urls.py` |
| **Template** | `app/chat/templates/chat/memory.html` |
| **Connection** | The view queries `MemoryBullet.objects.select_related("memory").filter(memory__user=profile)`. It applies optional search (`q`), type filter (`type`), and sort (`sort`) from GET parameters. An `ExpressionWrapper` annotation computes `affect = helpful_count - harmful_count`. The template renders a search bar, filter/sort controls, and a grid of memory cards with `{% for bullet in bullets %}...{% empty %}`. |

### Unit 5: Memory Detail (Scaffolded, Template Pending)

| Layer | Detail |
|---|---|
| **View** | `MemoryBulletsView` (Generic CBV, `DetailView`) in `app/chat/views.py` |
| **Model(s)** | `Memory`, `MemoryBullet`, `User` (profile) |
| **URL** | `path("m/<int:memory_id>/", views.MemoryBulletsView.as_view(), name="memory_detail")` in `app/chat/urls.py` |
| **Template** | `chat/memory_detail.html` (referenced in the view but the template file was removed during a recent cleanup; this route is non-functional until the template is recreated) |
| **Connection** | `DetailView` uses `pk_url_kwarg = "memory_id"` to look up a single `Memory`. The overridden `get_queryset()` filters by authenticated user and prefetches `memorybullet_set`. The template receives the `memory` object in context and displays its bullets. |
| **Status** | The view class and URL pattern remain registered, but visiting `/chat/m/<id>/` will raise a `TemplateDoesNotExist` error until a new `memory_detail.html` is created under `app/chat/templates/chat/`. |

### Unit 6: Login

| Layer | Detail |
|---|---|
| **View** | `login_view()` FBV in `app/users/views.py` |
| **Model(s)** | `auth.User` (via `services.authenticate_and_login()`) |
| **URL** | `path("login/", views.login_view, name="login")` in `app/users/urls.py` |
| **Template** | `app/users/templates/users/login_form.html` |
| **Connection** | GET returns the login form partial (for AJAX modal loading) or redirects to home. POST calls `services.authenticate_and_login()` which uses `django.contrib.auth.authenticate()` and `login()`. On success, returns `JsonResponse` (AJAX) or redirects. On failure, re-renders the form with an error message. |

### Unit 7: Registration

| Layer | Detail |
|---|---|
| **View** | `register_view()` FBV in `app/users/views.py` |
| **Model(s)** | `auth.User`, `User` (profile, via `services.create_user_with_profile()`) |
| **URL** | `path("register/", views.register_view, name="register")` in `app/users/urls.py` |
| **Template** | `app/users/templates/users/register_form.html` |
| **Connection** | GET returns the registration form partial. POST calls `services.register_and_login()` which validates input, creates `auth.User`, creates the `User` profile, and logs in. Supports both AJAX and standard redirect responses. |

### Unit 8: Profile

| Layer | Detail |
|---|---|
| **View** | `profile_view()` FBV in `app/users/views.py` |
| **Model(s)** | `User` (profile), `auth.User` |
| **URL** | `path("profile/", views.profile_view, name="profile")` in `app/users/urls.py` |
| **Template** | `app/users/templates/users/profile.html` |
| **Connection** | Protected by `@login_required`. GET renders the profile page with current email and profile image. POST handles two actions: email update (`save_email`) and profile image upload (`save_account`). The template extends `base.html` and displays form fields for each setting. |

### Unit 9: Password Change

| Layer | Detail |
|---|---|
| **View** | `change_password_view()` FBV in `app/users/views.py` |
| **Model(s)** | `auth.User` |
| **URL** | `path("password-change/", views.change_password_view, name="password_change")` in `app/users/urls.py` |
| **Template** | `app/users/templates/users/password_change_form.html` |
| **Connection** | Protected by `@login_required`. GET returns the form partial for AJAX. POST validates current password, checks new password match, calls `set_password()` and `update_session_auth_hash()`. Supports AJAX (`JsonResponse`) and standard redirect to profile. |

---

## Team Notes, Reminders, and Challenges

### Reminders

- Always run `python manage.py migrate` after pulling changes that include new migration files.
- Copy `.env.example` to `.env` and fill in `DJANGO_SECRET_KEY` before running the project.
- The `feature/template` branch is the active development branch for UI work.
- The billing app (`app/billing/`) has models defined and migrated but no views or templates yet; it is scaffolded for future subscription and payment features.

### Challenges Encountered

**1. Template directory reorganization (three iterations)**

The template directory structure went through three major reorganizations between Feb 4 and Feb 6. The first layout placed all templates in a top-level `templates/` directory alongside frontend build tooling (Vite, Tailwind, React). The second iteration moved everything into `app/memoria/templates/`, colocating templates with the memoria app. The final structure settled on a hybrid approach: `templates/base.html` lives at the project root for global inheritance, the standalone landing page sits at `memoria/templates/memoria/landing.html`, and each app owns its templates under `app/<name>/templates/<name>/`. Each reorganization required updating `TEMPLATES["DIRS"]` in `base.py`, fixing all `{% extends %}` and `{% include %}` paths, and verifying that Django's template loader resolved every reference correctly.

**2. Frontend tooling pivot**

The project initially adopted a Vite + Tailwind CSS + React stack for frontend development, housed in a dedicated `frontend/` directory with `package.json`, `postcss.config.js`, `tailwind.config.js`, and `vite.config.js`. A `ChatPane.jsx` React component and compiled JavaScript bundles were generated for the chat interface. Over the course of development, the team determined that the overhead of maintaining a separate JavaScript build pipeline was not justified for the current scope of the application. The entire `frontend/` directory was removed, and all styling was migrated to vanilla CSS files under `static/css/` and app-level `static/` directories. Interactive behavior was consolidated into a single `static/js/main.js` file using plain JavaScript. This simplification reduced build complexity and eliminated the Node.js dependency from the development workflow.

**3. AJAX dual-mode views**

Every authentication view (`login_view`, `register_view`, `change_password_view`) needed to support two distinct request modes. When called via AJAX (identified by the `X-Requested-With: XMLHttpRequest` header), the view returns either a `JsonResponse` with success/error data or an HTML partial suitable for injection into a modal on the landing page. When called via a standard form submission, the view returns a full redirect. Implementing this pattern consistently required careful branching in each view function, separate template partials that render without extending `base.html`, and JavaScript on the landing page to intercept form submissions and route them through `fetch()`. The `ConversationMessagesView.post()` method follows the same dual-mode pattern for chat message creation.

**4. Sidebar collapse and content alignment**

The collapsible sidebar required coordination across three layers. The CSS in `static/css/base.css` defines the sidebar width, transition timing, and the `left` offset of the `.main-content` container. The JavaScript in `static/js/main.js` toggles a CSS class on the sidebar element and dynamically adjusts the main content positioning so that the content area expands to fill the freed space. A persistent issue emerged where the main content `div` did not reposition correctly when the sidebar was collapsed, leaving a gap on the left side of the page. Resolving this required synchronizing the CSS `transition` duration with the JavaScript class toggle and ensuring that the `left` property on `.main-content` matched the collapsed sidebar width exactly.

**5. Profile image upload pipeline**

Supporting user-uploaded profile images introduced several interconnected requirements. The `User` profile model defines a `profile_img` field with a custom `avatar_upload_to` function that generates unique file paths. The `Pillow` library is required for Django's `ImageField` validation. When a user uploads a new image, the view must delete the previous file from disk to prevent orphaned media accumulating on the server. The `<img>` tag in the navbar avatar uses a cache-busting query parameter (appending a timestamp) to force browsers to load the updated image rather than serving a stale cached version. The profile page template handles both the default avatar fallback and the uploaded image display path.

**6. Context processor for sidebar session list**

The sidebar in `base.html` displays a list of the authenticated user's conversation sessions. Rather than passing the session queryset from every view that renders a page extending `base.html`, the team implemented a custom context processor at `app/chat/context_processors.user_sessions`. This function checks whether the user is authenticated, retrieves the associated `User` profile, and queries `Session.objects.filter(user=profile).order_by("-updated_at")`. The context processor is registered in `TEMPLATES["OPTIONS"]["context_processors"]` in `base.py`, ensuring the `sessions` variable is available in every template context automatically. A custom template filter (`relative_time` in `chat_extras`) formats session timestamps as human-readable relative times (e.g., "2 hours ago") in the sidebar listing.

---

## Future Plan

### Billing and Subscription System

The `app/billing/` app is scaffolded with three models (`Plan`, `Subscription`, `Payment`) and initial migrations, but no views, URLs, or templates exist yet. The next phase will implement subscription plan selection, payment processing integration, and account management views to support tiered access to MEMORIA features.

### AI Agent Integration

The `create_user_message_with_agent_reply()` service in `app/chat/service.py` currently creates a placeholder assistant message with static content. The next step is to connect this service to a real LLM backend, sending the conversation history along with retrieved memory context to generate meaningful agent responses. This integration will require API key management, token usage tracking, and error handling for external service failures.

### Memory Extraction Pipeline

The LTMBSE-ACE algorithm described in the project abstract has not yet been implemented in code. Building the memory extraction pipeline will involve analyzing conversation content after each exchange to identify extractable facts, preferences, procedures, and episodic experiences. Extracted content will be classified by `MemoryType` (semantic, episodic, procedural), assigned initial strength scores, and stored as `MemoryBullet` records linked to the user's `Memory` object.

### Memory Detail Template

The `MemoryBulletsView` class and its URL pattern (`/chat/m/<int:memory_id>/`) remain registered, but the `memory_detail.html` template was removed during a recent cleanup. Recreating this template is required before the memory detail route becomes functional.

### Frontend Polish and Accessibility

Current CSS is functional but lacks responsive breakpoints for mobile and tablet viewports. Planned improvements include responsive layout adjustments, a dark mode toggle with CSS custom properties, keyboard navigation support for the sidebar and modal interactions, and ARIA attributes for screen reader accessibility across all interactive components.

### Testing

The project currently has database unit tests in `unit_test/database_unit_test.py` but lacks coverage for views, services, and template rendering. Planned test additions include unit tests for each view function and class (verifying correct template selection, context data, and HTTP status codes), service layer tests for `authenticate_and_login`, `register_and_login`, and `create_user_message_with_agent_reply`, and integration tests that exercise the full request cycle from URL dispatch through template rendering.

---

## Bonus Reflections

### HttpResponse vs. render()

Two FBV patterns coexist in MEMORIA:

1. **`HttpResponse` with `loader.get_template()`** (used by `home()`, `landing()`): The view explicitly loads the template object, calls `.render(context, request)`, and wraps the result in `HttpResponse`. This is the lower-level pattern that exposes each step of the rendering pipeline.

2. **`render()` shortcut** (used by `login_view()`, `profile_view()`, `memory_view()`, etc.): Django's `render(request, template_name, context)` combines template loading, rendering, and HttpResponse creation into a single call. It also automatically includes context processors and handles `RequestContext`.

Both produce the same output. The `render()` shortcut is more concise and is the conventional choice for most views. The explicit `HttpResponse` pattern is useful when a view needs to manipulate the response object (headers, status code) before returning it, or when demonstrating how Django's template rendering works at a lower level.

### Base CBV (View) vs. Generic CBV (DetailView)

Two CBV patterns are demonstrated:

1. **`ConversationMessagesView(View)`**: Subclasses Django's base `View` class. The developer defines explicit `get()` and `post()` methods with full control over query construction, context assembly, and response type. This is similar to writing an FBV but with the organizational benefits of a class (method dispatch, decorator application via `@method_decorator`).

2. **`MemoryBulletsView(DetailView)`**: Subclasses `DetailView`, a generic class-based view. The developer declares `model`, `template_name`, `context_object_name`, and `pk_url_kwarg` as class attributes. Django handles object lookup, 404 responses, and context injection automatically. The only customization needed is overriding `get_queryset()` to add the user filter and prefetching.

The tradeoff is control vs. convention. `View` provides maximum flexibility but requires more code. `DetailView` requires minimal code for standard single-object display patterns but is less transparent about what happens during request processing. MEMORIA uses `View` for the conversation page (which needs both GET and POST with custom logic) and `DetailView` for the memory detail page (which only needs to display a single object with related data).
