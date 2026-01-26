import pandas as pd
import mysql.connector
import matplotlib.pyplot as plt

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="root",
    database="flytau2"
)

query = """
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


"""

df = pd.read_sql(query, conn)
conn.close()

# הופכים ל"Wide" כדי שיהיה קל לצייר stacked
pv = df.pivot_table(
    index=["Size", "Manufacturer"],
    columns="Class_type",
    values="price",
    aggfunc="sum",
    fill_value=0
)
colors = ["#A7C7E7", "#A8D5BA"]  # כחול פסטל, ירוק פסטל (לפי סדר העמודות)

# במקום stacked=True
ax = pv.plot(kind="bar", stacked=False, figsize=(12,5), color=colors)

ax.set_xticklabels(ax.get_xticklabels(), rotation=0, ha="center")
ax.set_title("Revenue by Plane Size & Manufacturer (grouped by Class)")
ax.set_xlabel("Size × Manufacturer")
ax.set_ylabel("Revenue")
plt.tight_layout()
plt.show()


import mysql.connector as mdb
import pandas as pd
import matplotlib.pyplot as plt

# 1) התחברות
conn = mdb.connect(
    host="localhost",
    user="root",
    password="root",
    database="flytau2",
    port=3306
    )
query = """
SELECT
	p.Employee_id,
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
"""

df = pd.read_sql(query, conn)
conn.close()

import numpy as np
import matplotlib.pyplot as plt

# 3) סידור נתונים
df["sum_short_duration"] = pd.to_numeric(df["sum_short_duration"], errors="coerce").fillna(0)
df["sum_long_duration"] = pd.to_numeric(df["sum_long_duration"], errors="coerce").fillna(0)
df["total"] = df["sum_short_duration"] + df["sum_long_duration"]
df = df.sort_values("total", ascending=False)

# 4) גרף grouped bar (לא stacked)
labels = df["Employee_id"].astype(str).to_numpy()
short = df["sum_short_duration"].to_numpy()
long_  = df["sum_long_duration"].to_numpy()

idx = np.arange(len(labels))
w = 0.4  # רוחב עמודה

short_color = "#66C2A5"  # ירקרק-טורקיז פסטלי
long_color  = "#FC8D62"  # כתמתם-קורל פסטלי

plt.figure(figsize=(10, 5))
plt.bar(idx - w/2, short, width=w, label="Short-haul", color=short_color)
plt.bar(idx + w/2, long_,  width=w, label="Long-haul",  color=long_color)

plt.title("Total Flight Time per Employee (Short vs Long)")
plt.xlabel("Employee_id")
plt.ylabel("Duration")
plt.xticks(idx, labels, rotation=0)
plt.legend()
plt.tight_layout()
plt.show()




