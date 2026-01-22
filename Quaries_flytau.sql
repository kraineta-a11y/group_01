

SELECT AVG(t.occupancy_pct) AS avg_occupancy_pct
FROM (
    SELECT
        f.Flight_number,
        100.0 * SUM(s.Availability = 1) / COUNT(*) AS occupancy_pct
    FROM Flight f
    JOIN Seats_in_flight s
      ON f.Flight_number = s.Flight_number
     AND f.Plane_id = s.Plane_id
    WHERE f.Flight_status = 'LANDED'
    GROUP BY f.Flight_number
) AS t;




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

-- מחיר למחלקה בטיסה (מכווץ כדי למנוע הכפלות אם יש כמה רשומות תמחור)
LEFT JOIN (
    SELECT Flight_number, Plane_id, Class_type, MAX(Price) AS Price
    FROM Flight_pricing
    GROUP BY Flight_number, Plane_id, Class_type
) fp
  ON fp.Flight_number = f.Flight_number
 AND fp.Plane_id     = f.Plane_id
 AND fp.Class_type   = c.Class_type

-- הזמנות: LEFT JOIN כדי לא להפיל טיסות בלי הזמנות
LEFT JOIN Booking b
  ON b.Flight_number = f.Flight_number
 AND b.Booking_status IN ('ACTIVE', 'COMPLETED', 'CUSTOMER_CANCELLED')

-- מושבים שנמכרו: LEFT JOIN כדי לא להפיל טיסות/מחלקות בלי מכירות
LEFT JOIN Seats_in_order sio
  ON sio.Booking_number = b.Booking_number
 AND sio.Plane_id       = f.Plane_id
 AND sio.row_num BETWEEN c.first_row AND c.last_row
 AND sio.col_num BETWEEN c.first_col AND c.last_col

WHERE f.Flight_status IN ('LANDED', 'FULLY BOOKED', 'ACTIVE')
GROUP BY p.Size, p.Manufacturer, c.Class_type;




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

