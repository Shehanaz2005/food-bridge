# Food Bridge

Food Bridge is a full-stack Django platform that connects food donors, verified NGOs, and volunteers to rescue surplus food. Every listing, request, pickup, delivery, and confirmed receipt is stored in the database and follows a controlled workflow, so impact figures are based on real records rather than estimates.

The interface is built with server-rendered HTML5, CSS3, vanilla JavaScript, and Bootstrap 5. There is no separate frontend build step.

---

## Highlights

- Four role-specific workspaces: Food Donor, NGO, Volunteer, and Administrator.
- Real donation workflow from listing to NGO-confirmed completion.
- Rule-based Smart Food Matching with High, Medium, and Low indicators plus human-readable explanations.
- Automatic expiry monitoring that blocks unsafe food from being requested, assigned, or collected.
- Live donation journey tracker with AJAX status polling.
- In-app notifications for every important handoff.
- Database-backed impact analytics and administrator reporting.
- NGO verification, account blocking, object-level permissions, and an audit trail.
- Responsive public website, dashboards, and accessible forms.
- Automated test suite covering the main workflows and security rules.

---

## Technology

| Layer | Technology |
| --- | --- |
| Backend | Python 3.13, Django 5.2 |
| Database | SQLite by default; PostgreSQL supported through environment variables |
| Frontend | HTML5, CSS3, vanilla JavaScript, Bootstrap 5 |
| Icons and fonts | Font Awesome 6, Sora and Inter via Google Fonts |
| Images | Pillow for uploaded food photos and avatars |
| Authentication | Django authentication with a custom `accounts.User` model |

No React, Node.js, Express, or separate JavaScript bundler is required.

---

## Quick start

### 1. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Apply migrations

```bash
python manage.py migrate
```

### 4. Optional: load the demo dataset

```bash
python manage.py seed_demo
```

The command is safe to run once. If demo accounts already exist it changes nothing. To rebuild the demo dataset from scratch:

```bash
python manage.py seed_demo --reset
```

### 5. Start the development server

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

---

## Demo accounts

After running `seed_demo`:

| Role | Username | Password |
| --- | --- | --- |
| Administrator | `admin` | `AdminPass123!` |
| Food Donor | `spice_garden` | `FoodBridge123!` |
| Verified NGO | `anna_seva` | `FoodBridge123!` |
| Volunteer | `arjun_volunteer` | `FoodBridge123!` |

Additional demo accounts use the same `FoodBridge123!` password:

- Donors: `green_bowl`, `sunrise_bakery`
- NGOs: `roti_bank` (verified), `hope_kitchen` (pending verification)
- Volunteers: `priya_volunteer`, `samir_volunteer`

`--reset` deletes only the demo accounts listed in the seeder and their demo donations. Do not use this command against a production database.

---

## The rescue workflow

1. A donor creates a food donation with quantity, category, pickup details, preparation time, and a safe best-before time.
2. A verified NGO finds the food through search, filters, or Smart Food Matching and submits a request.
3. The donor accepts one request. Other pending requests for that donation are automatically declined.
4. An administrator assigns an available volunteer, or uses automatic assignment.
5. The volunteer accepts the pickup offer.
6. The volunteer marks the food as picked up.
7. The volunteer marks the food as delivered.
8. The recipient NGO confirms receipt. The donation becomes completed, the request becomes fulfilled, and the assignment is closed.

Status transitions are centralised in `donations/workflow.py`. Invalid transitions are rejected instead of being written directly by views.

### Donation statuses

`available → requested → accepted → assigned → picked_up → delivered → completed`

`expired` and `cancelled` are terminal states. Expiry can happen before pickup. Cancellation is allowed while the donation is available, requested, accepted, or assigned.

---

## Smart Food Matching

Matching is transparent and rule-based. The score is calculated from:

| Rule | Weight |
| --- | --- |
| Category preference | 35 points |
| Pickup city / service area | 25 points |
| Quantity against the NGO's preferred minimum | 25 points |
| Expiry urgency | 15 points |

- **High match:** 75–100
- **Medium match:** 50–74
- **Low match:** below 50

Every result includes the reasons behind the score. NGOs can also sort by newest, nearest expiry, or highest quantity.

---

## Expiry and food safety

- Expiry is checked whenever a donation page or dashboard is loaded, and by the `mark_expired_donations` management command.
- Overdue donations are moved to `expired`; pending and accepted requests are closed and any active assignment is cancelled.
- Expired food cannot be requested, assigned, picked up, or distributed.
- Donors, NGOs, and volunteers receive warnings for food expiring soon.
- Donors must provide preparation and best-before times; the form rejects past expiry times and expiry before preparation.
- Pickup addresses and phone numbers are hidden until an NGO request is accepted.

Run the expiry job manually:

```bash
python manage.py mark_expired_donations
```

Options:

```bash
python manage.py mark_expired_donations --warn-hours 6
python manage.py mark_expired_donations --no-warnings
```

For production, schedule this command every 15–30 minutes with cron, Windows Task Scheduler, or a process manager. The website also performs a lazy expiry check on relevant page loads, so the command is a safety net rather than the only protection.

---

## Role capabilities

### Food Donor

- Create, edit, and cancel donations while they are still editable.
- Review incoming NGO requests and accept or decline them.
- Track pickup and delivery progress.
- Receive notifications and view personal impact.
- View donation history and report problems.

### NGO

- Register and wait for administrator verification.
- Browse, search, filter, and sort available food.
- See explainable Smart Food Match scores.
- Request food once verified; duplicate requests are prevented.
- Track requests, confirm receipt after delivery, and view received quantities.

### Volunteer

- View offered and active pickup assignments.
- Accept or decline offers with a reason.
- Mark pickup and delivery.
- Toggle availability and view completed delivery history.
- See pickup contact details only when assigned.

### Administrator

- View live platform statistics and recent activity.
- Verify NGOs and block or unblock accounts.
- Monitor donations, requests, assignments, and reported issues.
- Assign volunteers manually or automatically.
- Review the audit trail and database-backed impact analytics.

---

## Security and access control

- Passwords are hashed by Django; password strength validators are enabled.
- Role-based decorators protect role dashboards and operational actions.
- Object-level rules decide who may view a donation, its private contact details, or its status API.
- All state-changing forms use CSRF protection.
- Server-side validation is applied to donations, requests, profiles, issues, and uploads.
- Uploaded images are limited to JPG, PNG, or WebP and 5 MB.
- Repeated failed sign-ins are throttled in the cache.
- Blocked accounts cannot sign in, and existing sessions are terminated by middleware.
- Destructive actions require POST and confirmation.
- Safe-redirect checks prevent open redirects from notification links and login.
- Administrative and workflow actions are recorded in an audit log.
- Production security settings switch on automatically when `DEBUG=False`: secure cookies, HTTPS redirect, HSTS, and proxy SSL headers.

---

## Notifications

Notifications are stored in the database and shown in the top bar, sidebar count, and notification centre. They are created for events such as:

- New requests and donor decisions
- Volunteer assignment, acceptance, and decline
- Pickup and delivery updates
- NGO verification
- Expiry warnings and expiry closure
- Account blocking, issue reports, and issue updates

Optional event keys prevent duplicate expiry or warning notifications.

---

## Configuration

Environment variables are read at startup. Defaults are suitable for local development.

| Variable | Purpose | Default |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Secret key | Generated once into `.secret_key` |
| `DJANGO_DEBUG` | Debug mode | `True` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts | `localhost,127.0.0.1,testserver` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins | empty |
| `DJANGO_TIME_ZONE` | Time zone | `Asia/Kolkata` |
| `DJANGO_EMAIL_BACKEND` | Email backend | Console backend |
| `DJANGO_SECURE_COOKIES` | Secure cookies when debug is off | `True` |
| `DJANGO_SSL_REDIRECT` | Redirect HTTP to HTTPS when debug is off | `True` |
| `DJANGO_HSTS_SECONDS` | HSTS duration | `31536000` |
| `DB_ENGINE` | `sqlite` or `postgresql` | `sqlite` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection | local defaults |

### PostgreSQL

Install a PostgreSQL driver in the active environment:

```bash
pip install "psycopg[binary]"
```

Then configure:

```powershell
$env:DB_ENGINE = "postgresql"
$env:DB_NAME = "food_bridge"
$env:DB_USER = "food_bridge"
$env:DB_PASSWORD = "your-password"
$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"
python manage.py migrate
```

The Django models use standard relational features and do not depend on SQLite-specific behaviour.

---

## Testing

Run the full suite:

```bash
python manage.py test
```

Run one app:

```bash
python manage.py test donations
```

The tests cover registration and login, role access, blocked accounts, NGO verification, profile updates, donation validation, object-level privacy, requests, acceptance and rejection, cancellation, volunteer assignment, pickup and delivery, completion, expiry, Smart Matching, notifications, the status API, audit filtering, issue reporting, and analytics.

The suite automatically uses a fast password hasher while testing, so a full run takes only a few seconds. Production password hashing is unchanged. You can also opt into the explicit test settings file:

```bash
python manage.py test --settings=food_bridge.test_settings
```

Useful validation commands:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
```

---

## Project structure

```text
food-bridge/
├── manage.py
├── requirements.txt
├── db.sqlite3                 # created locally, not committed
├── .secret_key                # created locally, not committed
├── food_bridge/               # settings, root URLs, error handlers, test factories
├── accounts/                  # custom user, profiles, auth, dashboards, admin users
├── donations/                 # donations, requests, workflow, matching, expiry
├── volunteers/                # pickup assignments and volunteer actions
├── tracking/                  # journey events, audit log, status API
├── notifications/             # in-app notification centre and helpers
├── analytics/                 # public impact pages and admin analytics
├── support/                   # issue reporting and admin issue management
├── templates/                 # shared, public, dashboard, and error templates
├── static/                    # design system CSS, JavaScript, favicon
└── media/                     # uploaded images at runtime
```

Main URL areas:

- `/` — public landing page
- `/impact/` — public impact dashboard
- `/accounts/register/`, `/accounts/login/` — authentication
- `/donations/` — donor donations
- `/donations/browse/` — NGO food discovery
- `/volunteer/assignments/` — volunteer workspace
- `/dashboard/admin/...` — operational administrator pages
- `/admin/` — Django admin for low-level database administration

---

## Design

The interface uses a forest-green primary palette, fresh orange accents, cream and white surfaces, rounded cards, and restrained shadows. The public site uses CSS and inline SVG artwork rather than stock-photo placeholders. Dashboards share a responsive sidebar shell with role-specific navigation, notification counts, status badges, and accessible focus states.

---

## Known boundaries

- Notifications are in-app only; no SMS or push provider is configured.
- Email uses Django's console backend unless a real backend is configured.
- Food-safety decisions remain the responsibility of donors and recipient organisations; the platform enforces timing and workflow rules but does not inspect food.
- The included demo dataset is for local review and must not be treated as production data.
