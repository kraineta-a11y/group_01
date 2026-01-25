# FLYTAU Airline Management System - AI Coding Guidelines

## Architecture Overview

**FLYTAU** is a Flask-based airline management system with MySQL backend. The system manages flights, crew scheduling, bookings, and seat allocation for both short-haul (<6 hours) and long-haul (>360 min) flights with distinct crew requirements.

### Core Components
- **`app.py`**: Flask application with 40+ routes organized into three user flows:
  - Admin routes: `/admin/*` (flight/crew management, reporting)
  - Client routes: `/` → `/checkout/*` → booking flow
  - Auth routes: `/login`, `/register`, `/logout`
- **`database.py`**: MySQL connection handler and business logic functions
- **`helpers.py`**: Utility functions for common operations (time normalization, seat generation, validation)
- **`templates/`**: Jinja2 HTML templates organized by feature
- **`static/`**: CSS and generated plots (revenue_plot.png, staff_hours_plot.png)

## Key Patterns & Conventions

### Database Access Pattern
All database operations use centralized `get_db_connection()` which connects to PythonAnywhere MySQL:
```python
conn = get_db_connection()
cursor = conn.cursor(dictionary=True)  # Always use dictionary=True for readability
# ... execute queries
cursor.close()
conn.close()
```
Always close connections explicitly. Use `conn.commit()` for modifications.

### Flight Classification Logic
**Long-haul flights** (Duration > 360 minutes) require:
- **3 pilots** (vs 2 for short-haul)
- **6 stewards** (vs 3 for short-haul)
- Large planes only (Size = 'LARGE')

Determined via `is_long_haul_flight(flight_number)` in helpers.py.

### Time Handling Quirk
The database stores `Departure_time` as MySQL TIMEDELTA. Normalize with:
```python
time_handle_normalize(departure_time)  # Returns datetime.time object
dep_dt = datetime.combine(departure_date, normalized_time)
```
Used extensively in `database.py` staff availability queries.

### Availability Checking (Critical Pattern)
`get_available_staff()` in `database.py` enforces two rules:
1. **No time conflicts**: Staff cannot be assigned to overlapping flights (checked via `TIMESTAMP(...) + INTERVAL Duration MINUTE`)
2. **Location continuity**: Staff's last landed flight must be at the origin airport of the new flight (prevents staff teleportation)

This pattern is wrapped by `get_available_pilots()` and `get_available_stewards()` with long-haul qualification checks.

### Pricing Lock Mechanism
Once a flight's economy price is set, it **cannot be edited**. Business price is locked after the first edit unless it exactly equals 1.5× economy price (default multiplier). Checked via `context['can_edit_economy']` and `context['can_edit_business']` flags in `build_edit_flight_context()`.

### Cancellation Policy
System-wide rule: Flights cannot be cancelled within **72 hours** of departure. Cancelling a flight:
1. Sets status to 'CANCELLED'
2. Cascades to all active bookings (status → 'SYSTEM_CANCELLED')
3. Removes all crew assignments
4. Zeros pricing

### Session Management
Flask-Session configured with **30-minute timeout**:
- Cookies are secure (`SESSION_COOKIE_SECURE=True`)
- User roles determined by session keys: `manager_employee_id` or `client_email` via `get_user_role(session)`
- Session data persists in `flask_session_data/` directory

### Error Handling
Custom `@handle_errors` decorator in helpers.py wraps route handlers—unhandled exceptions render `error.html` with error message.

## Feature-Specific Logic

### Seat Management
- Seats auto-generated based on Plane's Class configurations (row/col ranges)
- Seats mapped to seat classes (ECONOMY/BUSINESS) which have pricing
- Booking flow: passenger_count → passenger_details → seat_selection → order_summary → confirm_booking

### Booking Lifecycle
```
ACTIVE → (on flight LANDED) → COMPLETED
ACTIVE → (customer/system cancellation) → CUSTOMER_CANCELLED / SYSTEM_CANCELLED
```
Booking status auto-updated by `update_booking_status()` when flights land.

### Admin Graphs
Two matplotlib plots regenerated on `/admin/graphs`:
1. **Revenue by Plane Size & Manufacturer** (grouped bar chart, handles cancellation refunds @ 5%)
2. **Staff Flight Hours** (short vs long-haul hours per employee)

## Critical Files to Know

| File | Purpose |
|------|---------|
| `app.py:handle_flight_update()` | Processes flight edits with pricing lock enforcement |
| `app.py:admin_create_flight()` | Creates flights and initializes crew requirements |
| `database.py:get_available_staff()` | Finds crew without time conflicts or location issues |
| `database.py:build_edit_flight_context()` | Prepares all data for flight edit form |
| `helpers.py:time_handle_normalize()` | Converts various time formats to datetime.time |
| `app.py:confirm_booking()` | Finalizes booking, creates Seats_in_order records |

## Common Developer Workflows

### Add a new admin route
1. Create route with `@application.route()` and `@handle_errors` decorators
2. Check role: `if get_user_role(session) != 'manager': abort(403)`
3. Fetch data via `get_db_connection()`, render template

### Modify crew assignment logic
- Change crew size requirements in `handle_crew_update()` validation (lines ~170)
- Update long-haul detection in `is_long_haul_flight()` (threshold: 360 min)
- Adjust availability queries in `get_available_staff()` if adding new constraints

### Extend availability rules
Edit `get_available_staff()` query (database.py) — currently checks:
- Time overlap with existing assignments
- Location continuity (last flight destination = new flight origin)

### Add booking cancellation refund logic
Modify the `CUSTOMER_CANCELLED` refund calculation in `/admin/graphs` query (currently 5% penalty) and `confirm_booking()` flow.

## Testing Considerations

**No automated tests present.** Manual testing should cover:
1. **Long-haul crew assignment** (must enforce 3 pilots, 6 stewards)
2. **Availability conflicts** (staff assigned to overlapping flights)
3. **72-hour cancellation rule** (near-departure flights)
4. **Pricing lock** (economy price immutable after first set)
5. **Seat generation** (ensure seats created for all flights)
