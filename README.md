

# FLYTAU ✈️ – Airline Booking & Management System (Flask + MySQL)

**Live website:** https://netarosh.pythonanywhere.com/  
**Repository:** https://github.com/kraineta-a11y/group_01/tree/main
---


## מה אפשר לעשות באתר

### גלישה כ-Guest
בדף הבית אפשר לגלוש כאורח/ת (Guest) ולחפש טיסות. בדף הבית מופיע גם Tip שמסביר שאפשר ללחוץ **Search** בלי למלא שדות כדי לראות את כל הטיסות הזמינות. 
### Login / Register
קיים מסך התחברות ייעודי, עם קישור להרשמה (Register). 
### Manage Booking (ניהול הזמנה)
מהדף הראשי יש גישה ל-**Manage Bookings** ומסך שבו מזינים **Booking number** ו-**Email** כדי לצפות בהזמנה קיימת. 

### Seat Selection (בחירת מושבים)
בריפו קיימת תבנית בשם `seat_selection.html` (בתיקיית `templates`) המייצגת ממשק בחירת מושב/ים לפי זמינות.  
המערכת מעדכנת מושבים כתפוסים/פנויים בהתאם להזמנה ולחוקים שהוגדרו.

> הערה: שם הקובץ מופיע לפי הריפו (תיקיית templates והעדכונים שבוצעו בה).

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

(פירוט הדוחות נמצא בקובץ השאילתות ובסקריפט הוויזואליזציה. )

---

## טכנולוגיות
- **Backend:** Python + Flask 
- **Database:** MySQL (schema + data ב-SQL dump)  
- **Frontend:** HTML (Jinja Templates) + CSS   
- **Deployment:** PythonAnywhere

---
.
:



