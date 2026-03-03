import os
import re
import psycopg2
import pandas as pd
from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from pdfminer.high_level import extract_text
from docx import Document

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
APP_PASSWORD = os.getenv("APP_PASSWORD")


# ------------------ DATABASE CONNECTION ------------------

def get_connection():
    return psycopg2.connect(DATABASE_URL)


# ------------------ EXTRACTION LOGIC ------------------

def extract_fields(text):

    # -------- Amount Detection --------
    amount = None

    # ₹ format
    amount_match = re.search(r'₹\s?[\d,]+', text)
    if amount_match:
        raw = amount_match.group()
        clean = raw.replace("₹", "").replace(",", "").strip()
        try:
            amount = float(clean)
        except:
            amount = None

    # Lakh format
    lakh_match = re.search(r'₹?\s?([\d\.]+)\s*lakh', text, re.IGNORECASE)
    if lakh_match:
        try:
            amount = float(lakh_match.group(1)) * 100000
        except:
            pass

    # -------- Financial Year --------
    fy_match = re.search(r'20\d{2}[-–]\d{2}', text)
    financial_year = fy_match.group() if fy_match else ""

    # -------- Institute Detection --------
    institute_match = re.search(r'NSTI\s?\(.*?\),?\s?[A-Za-z]+', text)
    institute = institute_match.group() if institute_match else ""

    # -------- Object Head --------
    object_head_match = re.search(r'Professional Services\s?\(\d+\)', text)
    object_head = object_head_match.group() if object_head_match else ""

    # -------- Subject --------
    subject_match = re.search(r'Administrative Approval.*?Sanction.*', text)
    subject = subject_match.group() if subject_match else ""

    return {
        "amount": amount,
        "financial_year": financial_year,
        "object_head": object_head,
        "institute": institute,
        "subject": subject
    }


# ------------------ LOGIN ------------------

@app.get("/", response_class=HTMLResponse)
def login_page():
    return """
    <h2>Approval Tracker Login</h2>
    <form method='post' action='/login'>
    <input type='password' name='password' placeholder='Enter Password'/>
    <button type='submit'>Login</button>
    </form>
    """


@app.post("/login")
def login(password: str = Form(...)):
    if password == APP_PASSWORD:
        return RedirectResponse("/profiles", status_code=303)
    return HTMLResponse("<h3>Wrong Password</h3>")


# ------------------ PROFILE MANAGEMENT ------------------

@app.get("/profiles", response_class=HTMLResponse)
def profiles():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM profiles")
    profiles = cur.fetchall()
    conn.close()

    html = "<h2>Select Profile</h2>"
    for p in profiles:
        html += f"<a href='/dashboard/{p[0]}'>{p[1]}</a><br>"

    html += """
    <h3>Add New Profile</h3>
    <form method='post' action='/add_profile'>
    <input name='name' placeholder='Profile Name'/>
    <button type='submit'>Add</button>
    </form>
    """
    return html


@app.post("/add_profile")
def add_profile(name: str = Form(...)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO profiles (name) VALUES (%s)", (name,))
    conn.commit()
    conn.close()
    return RedirectResponse("/profiles", status_code=303)


# ------------------ DASHBOARD ------------------

@app.get("/dashboard/{profile_id}", response_class=HTMLResponse)
def dashboard(profile_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM approvals WHERE profile_id=%s", (profile_id,))
    count = cur.fetchone()[0]
    conn.close()

    return f"""
    <h2>Dashboard</h2>
    <p>Total Entries: {count}</p>
    <a href='/upload/{profile_id}'>Upload Noting</a><br>
    <a href='/export/{profile_id}'>Export Excel</a><br>
    <a href='/profiles'>Back to Profiles</a>
    """


# ------------------ FILE UPLOAD ------------------

@app.get("/upload/{profile_id}", response_class=HTMLResponse)
def upload_page(profile_id: int):
    return f"""
    <h2>Upload Noting</h2>
    <form action="/process/{profile_id}" method="post" enctype="multipart/form-data">
    <input type="file" name="file"/>
    <button type="submit">Upload</button>
    </form>
    """


@app.post("/process/{profile_id}")
async def process_file(profile_id: int, file: UploadFile = File(...)):
    content = await file.read()
    text = ""

    if file.filename.endswith(".pdf"):
        file_path = "/tmp/temp.pdf"
        with open(file_path, "wb") as f:
            f.write(content)
        text = extract_text(file_path)
        os.remove(file_path)

    elif file.filename.endswith(".docx"):
        file_path = "/tmp/temp.docx"
        with open(file_path, "wb") as f:
            f.write(content)
        doc = Document(file_path)
        text = "\n".join([p.text for p in doc.paragraphs])
        os.remove(file_path)

    else:
        text = content.decode()

    extracted = extract_fields(text)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO approvals 
        (profile_id, institute, subject, amount, financial_year, object_head)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        profile_id,
        extracted["institute"],
        extracted["subject"],
        extracted["amount"],
        extracted["financial_year"],
        extracted["object_head"]
    ))

    conn.commit()
    conn.close()

    return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)


# ------------------ EXPORT EXCEL ------------------

@app.get("/export/{profile_id}")
def export_excel(profile_id: int):
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM approvals WHERE profile_id={profile_id}", conn)
    conn.close()

    file_path = f"/tmp/export_{profile_id}.xlsx"
    df.to_excel(file_path, index=False)

    return FileResponse(
        path=file_path,
        filename=f"Approval_Export_{profile_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


