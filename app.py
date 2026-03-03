import os
import re
import psycopg2
import pandas as pd
from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pdfminer.high_level import extract_text
from docx import Document
from datetime import datetime

app = FastAPI()
templates = Jinja2Templates(directory="templates")

DATABASE_URL = os.getenv("DATABASE_URL")
PASSWORD = os.getenv("APP_PASSWORD")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def extract_fields(text):
    amount_match = re.search(r'₹?\s?[\d,]+', text)

    amount = None
    if amount_match:
        raw_amount = amount_match.group()
        clean_amount = raw_amount.replace("₹", "").replace(",", "").strip()
        try:
            amount = float(clean_amount)
        except:
            amount = None

    fy_match = re.search(r'20\d{2}-\d{2}', text)
    fy = fy_match.group() if fy_match else ""

    object_head_match = re.search(r'Head\s?\d+|\d{4}\.\d+\.\d+', text)
    object_head = object_head_match.group() if object_head_match else ""

    return {
        "amount": amount,
        "financial_year": fy,
        "object_head": object_head
    }

    fy_match = re.search(r'20\d{2}-\d{2}', text)
    fy = fy_match.group() if fy_match else ""

    object_head_match = re.search(r'Head\s?\d+|\d{4}\.\d+\.\d+', text)
    object_head = object_head_match.group() if object_head_match else ""

    return {
        "amount": amount,
        "financial_year": fy,
        "object_head": object_head
    }

@app.get("/", response_class=HTMLResponse)
def login_page():
    return """
    <form method='post' action='/login'>
    <input type='password' name='password' placeholder='Enter Password'/>
    <button type='submit'>Login</button>
    </form>
    """

@app.post("/login")
def login(password: str = Form(...)):
    if password == PASSWORD:
        return RedirectResponse("/profiles", status_code=303)
    return "Wrong password"

@app.get("/profiles", response_class=HTMLResponse)
def profiles():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM profiles")
    data = cur.fetchall()
    conn.close()

    html = "<h2>Select Profile</h2>"
    for p in data:
        html += f"<a href='/dashboard/{p[0]}'>{p[1]}</a><br>"
    html += """
    <form method='post' action='/add_profile'>
    <input name='name' placeholder='New Profile Name'/>
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

@app.get("/dashboard/{profile_id}", response_class=HTMLResponse)
def dashboard(profile_id: int):
    return f"""
    <h2>Dashboard</h2>
    <a href='/upload/{profile_id}'>Upload Noting</a><br>
    <a href='/export/{profile_id}'>Export Excel</a>
    """

@app.get("/upload/{profile_id}", response_class=HTMLResponse)
def upload_page(profile_id: int):
    return f"""
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
        with open("/tmp/temp.pdf", "wb") as f:
            f.write(content)
        text = extract_text("/tmp/temp.pdf")
        os.remove("/tmp/temp.pdf")

    elif file.filename.endswith(".docx"):
        with open("/tmp/temp.docx", "wb") as f:
            f.write(content)
        doc = Document("/tmp/temp.docx")
        text = "\n".join([p.text for p in doc.paragraphs])
        os.remove("/tmp/temp.docx")

    else:
        text = content.decode()

    extracted = extract_fields(text)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO approvals (profile_id, amount, financial_year, object_head)
        VALUES (%s, %s, %s, %s)
    """, (profile_id, extracted["amount"], extracted["financial_year"], extracted["object_head"]))
    conn.commit()
    conn.close()

    return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)

from fastapi.responses import FileResponse

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
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM approvals WHERE profile_id={profile_id}", conn)
    conn.close()
    file_name = f"export_{profile_id}.xlsx"
    df.to_excel(file_name, index=False)

    return RedirectResponse(f"/dashboard/{profile_id}", status_code=303)


