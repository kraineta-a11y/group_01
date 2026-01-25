
-- Quary 1 --
USE flytau2;

SELECT AVG(occ_pct) AS avg_occupancy_pct
FROM (
    SELECT
        f.Flight_number,
        100.0 * SUM(s.Availability = 0) / COUNT(*) AS occ_pct
    FROM Flight f
    JOIN Seats_in_flight s
      ON s.Flight_number = f.Flight_number
     AND s.Plane_id      = f.Plane_id
    WHERE f.Flight_status = 'LANDED'
    GROUP BY f.Flight_number
) t;


-- Quary 2 --

SELECT
    COALESCE(SUM(
        CASE
            WHEN sio.Booking_number IS NULL THEN 0
            WHEN b.Booking_status = 'CUSTOMER_CANCELLED' THEN fp.Price * 0.05
            ELSE fp.Price
        END
    ), 0) AS price,
    p.Size,
    p.Manufacturer,
    c.Class_type
FROM Flight f
JOIN Plane p
  ON p.Plane_id = f.Plane_id
JOIN Class c
  ON c.Plane_id = f.Plane_id

LEFT JOIN (
    SELECT Flight_number, Plane_id, Class_type, MAX(Price) AS Price
    FROM Flight_pricing
    GROUP BY Flight_number, Plane_id, Class_type
) fp
  ON fp.Flight_number = f.Flight_number
 AND fp.Plane_id     = f.Plane_id
 AND fp.Class_type   = c.Class_type


LEFT JOIN Booking b
  ON b.Flight_number = f.Flight_number
 AND b.Booking_status IN ('ACTIVE', 'COMPLETED', 'CUSTOMER_CANCELLED')

LEFT JOIN Seats_in_order sio
  ON sio.Booking_number = b.Booking_number
 AND sio.Plane_id       = f.Plane_id
 AND sio.row_num BETWEEN c.first_row AND c.last_row
 AND sio.col_num BETWEEN c.first_col AND c.last_col

WHERE f.Flight_status IN ('LANDED', 'FULLY BOOKED', 'ACTIVE')
GROUP BY p.Size, p.Manufacturer, c.Class_type;

-- Quary 3 --
SELECT
    p.Employee_id,
    'PILOT' AS role,
    COALESCE(SUM(CASE
        WHEN fr.Duration <= 360 THEN fr.Duration / 60.0
        ELSE 0
    END), 0) AS sum_short_duration,
    COALESCE(SUM(CASE
        WHEN fr.Duration > 360 THEN fr.Duration / 60.0
        ELSE 0
    END), 0) AS sum_long_duration
FROM Pilot p
LEFT JOIN Pilots_in_flight pif
    ON pif.Employee_id = p.Employee_id
LEFT JOIN Flight f
    ON f.Flight_number = pif.Flight_number
   AND f.Flight_status = 'LANDED'
LEFT JOIN Flying_route fr
    ON fr.Route_id = f.Route_id
GROUP BY p.Employee_id

UNION ALL

SELECT
    s.Employee_id,
    'STEWARD' AS role,
    COALESCE(SUM(CASE
        WHEN fr.Duration <= 360 THEN fr.Duration / 60.0
        ELSE 0
    END), 0) AS sum_short_duration,
    COALESCE(SUM(CASE
        WHEN fr.Duration > 360 THEN fr.Duration / 60.0
        ELSE 0
    END), 0) AS sum_long_duration
FROM Steward s
LEFT JOIN Stewards_in_flight sif
    ON sif.Employee_id = s.Employee_id
LEFT JOIN Flight f
    ON f.Flight_number = sif.Flight_number
   AND f.Flight_status = 'LANDED'
LEFT JOIN Flying_route fr
    ON fr.Route_id = f.Route_id
GROUP BY s.Employee_id;

-- Quary 4 --
SELECT
  DATE_FORMAT(Booking_date, '%Y-%m') AS ym,
  ROUND(
    100.0 * SUM(Booking_status = 'CUSTOMER_CANCELLED') / COUNT(*),
    2
  ) AS cancellation_rate_pct
FROM Booking
GROUP BY ym
ORDER BY ym;

-- Quary 5 --
WITH base AS (
    SELECT
        f.Plane_id,
        f.Flight_status,
        f.Departure_date,
        f.Departure_time,
        r.Origin_airport,
        r.Destination_airport,
        FLOOR((TO_DAYS(f.Departure_date) - TO_DAYS('2000-01-01')) / 30) AS dep_mi,
        DATE(DATE_ADD(TIMESTAMP(f.Departure_date, f.Departure_time), INTERVAL r.Duration MINUTE)) AS arr_date,
        FLOOR((
            TO_DAYS(DATE(DATE_ADD(TIMESTAMP(f.Departure_date, f.Departure_time), INTERVAL r.Duration MINUTE)))
            - TO_DAYS('2000-01-01')
        ) / 30) AS arr_mi
    FROM Flight f
    JOIN Flying_route r ON r.Route_id = f.Route_id
),
months AS (
    SELECT Plane_id, dep_mi AS mi
    FROM base
    WHERE Flight_status IN ('LANDED','CANCELLED')
    GROUP BY Plane_id, dep_mi
    UNION
    SELECT Plane_id, arr_mi AS mi
    FROM base
    WHERE Flight_status = 'LANDED'
      AND arr_mi <> dep_mi
    GROUP BY Plane_id, arr_mi
),
stats AS (
    SELECT
        Plane_id,
        dep_mi AS mi,
        SUM(CASE WHEN Flight_status = 'LANDED' THEN 1 ELSE 0 END) AS performed_cnt,
        SUM(CASE WHEN Flight_status = 'CANCELLED' THEN 1 ELSE 0 END) AS cancelled_cnt
    FROM base
    WHERE Flight_status IN ('LANDED','CANCELLED')
    GROUP BY Plane_id, dep_mi
),
util AS (
    SELECT
        Plane_id,
        mi,
        COUNT(DISTINCT utilized_day) AS utilized_days
    FROM (
        SELECT
            Plane_id,
            dep_mi AS mi,
            Departure_date AS utilized_day
        FROM base
        WHERE Flight_status = 'LANDED'
        UNION ALL
        SELECT
            Plane_id,
            arr_mi AS mi,
            arr_date AS utilized_day
        FROM base
        WHERE Flight_status = 'LANDED'
          AND arr_date <> Departure_date
    ) d
    GROUP BY Plane_id, mi
),
route_cnt AS (
    SELECT
        Plane_id,
        dep_mi AS mi,
        Origin_airport,
        Destination_airport,
        COUNT(*) AS cnt
    FROM base
    WHERE Flight_status = 'LANDED'
    GROUP BY Plane_id, dep_mi, Origin_airport, Destination_airport
),
dr AS (
    SELECT
        Plane_id,
        mi,
        GROUP_CONCAT(
            CONCAT(Origin_airport, ' -> ', Destination_airport)
            ORDER BY Origin_airport, Destination_airport
            SEPARATOR ' | '
        ) AS dominant_routes
    FROM (
        SELECT
            rc.*,
            RANK() OVER (PARTITION BY Plane_id, mi ORDER BY cnt DESC) AS rnk
        FROM route_cnt rc
    ) t
    WHERE rnk = 1
    GROUP BY Plane_id, mi
)
SELECT
    m.Plane_id,
    CONCAT(2000 + (m.mi DIV 12), '-', LPAD((m.mi MOD 12) + 1, 2, '0')) AS ym,
    COALESCE(st.cancelled_cnt, 0) AS cancelled_cnt,
    COALESCE(st.performed_cnt, 0) AS performed_cnt,
    (COALESCE(u.utilized_days, 0) / 30.0) * 100 AS utilization_pct,
    dr.dominant_routes
FROM months m
LEFT JOIN stats st ON st.Plane_id = m.Plane_id AND st.mi = m.mi
LEFT JOIN util  u  ON u.Plane_id  = m.Plane_id AND u.mi  = m.mi
LEFT JOIN dr       ON dr.Plane_id = m.Plane_id AND dr.mi = m.mi
ORDER BY m.Plane_id, m.mi;
