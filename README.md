

# FLYTAU ✈️ – Airline Booking & Management System (Flask + MySQL)

**Live website:** https://netarosh.pythonanywhere.com/ :contentReference[oaicite:0]{index=0}  
**Repository:** https://github.com/kraineta-a11y/group_01/tree/main :contentReference[oaicite:1]{index=1}
---

## תוכן עניינים
- [מה אפשר לעשות באתר](#מה-אפשר-לעשות-באתר)
- [UI/UX חשובים](#uiux-חשובים)
- [Business Logic עיקרי](#business-logic-עיקרי)
- [טכנולוגיות](#טכנולוגיות)
- [איך מריצים מקומית](#איך-מריצים-מקומית)
- [מבנה הריפו והסבר על כל הקבצים](#מבנה-הריפו-והסבר-על-כל-הקבצים)
- [Queries ו-Visualization](#queries-ו-visualization)
- [Deployment](#deployment)
- [Contributors](#contributors)

---

## מה אפשר לעשות באתר

### גלישה כ-Guest
בדף הבית אפשר לגלוש כאורח/ת (Guest) ולחפש טיסות. בדף הבית מופיע גם Tip שמסביר שאפשר ללחוץ **Search** בלי למלא שדות כדי לראות את כל הטיסות הזמינות. :contentReference[oaicite:3]{index=3}

### Login / Register
קיים מסך התחברות ייעודי, עם קישור להרשמה (Register). :contentReference[oaicite:4]{index=4}

### Manage Booking (ניהול הזמנה)
מהדף הראשי יש גישה ל-**Manage Bookings** ומסך שבו מזינים **Booking number** ו-**Email** כדי לצפות בהזמנה קיימת. :contentReference[oaicite:5]{index=5}

### Seat Selection (בחירת מושבים)
בריפו קיימת תבנית בשם `seat_selection.html` (בתיקיית `templates`) המייצגת ממשק בחירת מושב/ים לפי זמינות.  
המערכת מעדכנת מושבים כתפוסים/פנויים בהתאם להזמנה ולחוקים שהוגדרו.

> הערה: שם הקובץ מופיע לפי הריפו (תיקיית templates והעדכונים שבוצעו בה). :contentReference[oaicite:6]{index=6}

---

## UI/UX חשובים

### לחיצה על לוגו החברה חוזרת לדף הבית
בכל הדפים המרכזיים מופיע לוגו של FLYTAU בפינה (Corner Logo).  
**הלוגו הוא קישור** שמחזיר תמיד ל-Home/Landing Page — כך שמשתמש לא “נתקע” במסך פנימי ויכול לחזור לדף הבית בלחיצה אחת.

### עקביות עיצובית
העיצוב מנוהל דרך תיקיית `static/` (CSS ותמונות). בריפו יש עדכונים לקובץ `style.css` שמחזיק את ה-layout וה-look & feel.

---

## Business Logic עיקרי
המערכת משלבת חוקים עסקיים שמונעים מצב “לא הגיוני” במסד ובאתר, לדוגמה:
- **Seating & Availability** – מושבים חייבים להיות עקביים מול הטיסה והמטוס, וזמינות מתעדכנת בהתאם להזמנה/ביטול.
- **Cancellation Policies** – ביטולים של לקוח/מערכת משפיעים על ההכנסה/דוחות (לפי המדיניות שהוגדרה בפרויקט).
- **Reports / Management Insights** – שאילתות SQL מתקדמות לניתוח תפעולי (תפוסה, הכנסות, ביטולים וכו’).

(פירוט הדוחות נמצא בקובץ השאילתות ובסקריפט הוויזואליזציה. :contentReference[oaicite:7]{index=7})

---

## טכנולוגיות
- **Backend:** Python + Flask :contentReference[oaicite:8]{index=8}  
- **Database:** MySQL (schema + data ב-SQL dump) :contentReference[oaicite:9]{index=9}  
- **Frontend:** HTML (Jinja Templates) + CSS :contentReference[oaicite:10]{index=10}  
- **Deployment:** PythonAnywhere :contentReference[oaicite:11]{index=11}

---

## איך מריצים מקומית

> אם כבר יש לכם MySQL מותקן מקומית + Python 3 – זה ה-flow המומלץ.

### 1) יצירת DB והעלאת schema+data
בריפו יש גיבוי מלא:
- `db-backup-Final.sql` :contentReference[oaicite:12]{index=12}

דוגמה (ב-MySQL CLI):
```sql
SOURCE db-backup-Final.sql;
