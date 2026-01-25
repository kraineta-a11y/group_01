ברור — הנה גרסה קצרה ממש (באנגלית), באותו מבנה:

## Project Overview

FLYTAU is an airline booking and management system built with a **MySQL** relational database and a **Flask (Python)** web app. It manages flights, planes, routes, customers (registered and guests), bookings, seating, pricing by class, and crew data, and supports management insights through advanced SQL queries.

## Project Goals

* Design and implement a normalized airline database.
* Support flight search, booking, and seat selection.
* Enforce business rules (cancellations, availability, flight status).
* Create advanced SQL reports and integrate them into the app.

## Technologies and Tools

MySQL Workbench, Python, Flask, HTML/CSS, GitHub, PythonAnywhere.

## Business Logic

* **Seating:** Row numbering is continuous across cabin classes.
* **Cancellations:** Customer cancellation ≥36h before takeoff → 5% fee; system cancellations → no revenue.
* **Flight status:** “Completed” only if takeoff time has passed; “FULL” means full occupancy, not necessarily completed.
* **Crew analysis:** Flights are classified as short/long by duration for workload reporting.
