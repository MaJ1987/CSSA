"""
app_full_final.py - CSSA Shift Swap (Production)

Reads roster from configured Google Sheet (Option A — Google Sheet only).
Supports:
- Login (select username) with Switch User for testing
- Dashboard (next 14 calendar days horizontal)
- Request Swap flow with partner auto-population and payback date
- Swap validation rules: no Night→Day without rest, max consecutive shifts, inexperienced limit, month range
- Admin panel: Pending approvals, Auto-declined, Override, History, Users & Roles
- Debug tab for diagnostics
- Export updated roster as Excel (download) after swaps applied (no automatic Google Sheets writeback)

Configured Google Sheet (your sheet):
SPREADSHEET_ID = "1vyOz94x5V2wW4464ax_YD-dlY6BKHNTZHoiJ0R2f4As"
GID = "1819085850"
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from io import BytesIO

st.set_page_config(page_title="CSSA Shift Swap (Final)", layout="wide")

# ---------------- Configuration ----------------
SPREADSHEET_ID = "1vyOz94x5V2wW4464ax_YD-dlY6BKHNTZHoiJ0R2f4As"
GID = "1819085850"
GSHEET_CSV = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={GID}"

COL_NAME = "Names"
COL_TEAM = "Teams"
COL_EXPERIENCE = "Experience"
COL_ROLE = "Roles"

ALLOWED_AUTO_CODES = set(["D","N","R","X","DC","NC","DDM","NDM"])
MAX_CONSECUTIVE = 6
ALLOWED_MONTH_RANGE = 1  # current + next month

# ---------------- Helpers ----------------
def parse_special_date_header(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        if ":" in s and "/" in s:
            year, rest = s.split(":", 1)
            candidate = f"{rest}/{year}"
            dt = pd.to_datetime(candidate, dayfirst=True, errors="coerce")
            if pd.notna(dt):
                return dt.date()
    except Exception:
        pass
    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.notna(dt):
            return dt.date()
    except Exception:
        pass
    try:
        sc = s.replace(",", "").replace(" ", "")
        if sc.replace(".", "", 1).isdigit():
            origin = datetime(1899, 12, 30)
            return (origin + timedelta(days=int(round(float(sc))))).date()
    except Exception:
        pass
    return None

def detect_date_columns(df):
    date_cols = []
    fixed = {COL_NAME.lower(), COL_TEAM.lower(), COL_EXPERIENCE.lower(), COL_ROLE.lower()}
    for col in df.columns:
        s = str(col).strip()
        if not s:
            continue
        if s.lower() in fixed:
            continue
        if parse_special_date_header(col) is not None:
            date_cols.append(col)
            continue
        vals = df[col].astype(str).str.strip().replace("nan","").dropna().head(8).tolist()
        score = sum(1 for v in vals if v and v.upper() in ALLOWED_AUTO_CODES.union({"OFF","XX","X","R"}))
        if score >= 2:
            date_cols.append(col)
    if not date_cols and len(df.columns) > 4:
        date_cols = list(df.columns[4:])
    return [c for c in df.columns if c in date_cols]

def label_for(col):
    d = parse_special_date_header(col)
    if d:
        return f"{d.day} {d.strftime('%b')}"
    return str(col).strip()

def df_to_excel_bytes(df):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Roster")
    return out.getvalue()

def make_username(name):
    name = str(name).strip()
    if not name:
        return ""
    parts = name.split()
    if len(parts) == 1:
        return parts[0].lower()
    return (parts[0] + parts[-1][0]).lower()

def is_night(code):
    return str(code).upper().strip() in ("N","NC","NDM")

def is_day(code):
    return str(code).upper().strip() in ("D","DC","DDM")

def count_consecutive(df, row_idx, date_cols, idx):
    def work(v):
        try:
            return is_day(v) or is_night(v)
        except Exception:
            return False
    left = 0; i = idx-1
    while i >= 0 and work(df.at[row_idx, date_cols[i]]):
        left += 1; i -= 1
    right = 0; i = idx+1
    while i < len(date_cols) and work(df.at[row_idx, date_cols[i]]):
        right += 1; i += 1
    return left + right + 1

def inexperienced_count(df, col_label, inexperienced_set):
    cnt = 0
    for r in range(len(df)):
        code = str(df.at[r, col_label]).upper().strip()
        if code in ("D","N","DC","NC"):
            name = str(df.at[r, df.columns[0]])
            if name in inexperienced_set:
                cnt += 1
    return cnt

def validate_swap(df, ra, ia, rb, ib, date_cols, inexperienced_set):
    reasons = []
    df2 = df.copy(deep=True)
    a_code = str(df2.at[ra, date_cols[ia]]).strip()
    b_code = str(df2.at[rb, date_cols[ib]]).strip()
    df2.at[ra, date_cols[ia]] = b_code
    df2.at[rb, date_cols[ib]] = a_code

    # N -> D rule
    if is_night(df2.at[ra, date_cols[ia]]) and ia+1 < len(date_cols) and is_day(df2.at[ra, date_cols[ia+1]]):
        reasons.append("Requester would have Night→Day without rest.")
    if is_night(df2.at[rb, date_cols[ib]]) and ib+1 < len(date_cols) and is_day(df2.at[rb, date_cols[ib+1]]):
        reasons.append("Partner would have Night→Day without rest.")

    # Max consecutive
    if count_consecutive(df2, ra, date_cols, ia) > MAX_CONSECUTIVE:
        reasons.append("Requester would exceed max consecutive shifts (>6).")
    if count_consecutive(df2, rb, date_cols, ib) > MAX_CONSECUTIVE:
        reasons.append("Partner would exceed max consecutive shifts (>6).")

    # inexperienced limit
    if inexperienced_count(df2, date_cols[ia], inexperienced_set) > 1:
        reasons.append("More than 1 inexperienced controller on requester's date.")
    if inexperienced_count(df2, date_cols[ib], inexperienced_set) > 1:
        reasons.append("More than 1 inexperienced controller on partner's date.")

    # month range
    try:
        ca = parse_special_date_header(date_cols[ia])
        cb = parse_special_date_header(date_cols[ib])
        today = date(2026, 1, 1)
        def month_diff(d):
            return (d.year - today.year)*12 + (d.month - today.month)
        if ca is None or cb is None or month_diff(ca) < 0 or month_diff(ca) > ALLOWED_MONTH_RANGE or month_diff(cb) < 0 or month_diff(cb) > ALLOWED_MONTH_RANGE:
            reasons.append("Swaps allowed only for current and next month.")
    except Exception:
        pass

    return reasons

# ---------------- Session state ----------------
if "df" not in st.session_state:
    st.session_state.df = None
if "date_cols" not in st.session_state:
    st.session_state.date_cols = []
if "display_map" not in st.session_state:
    st.session_state.display_map = {}
if "users" not in st.session_state:
    st.session_state.users = {}
if "logged_user" not in st.session_state:
    st.session_state.logged_user = None
if "inexperienced" not in st.session_state:
    st.session_state.inexperienced = set()
if "swap_requests" not in st.session_state:
    st.session_state.swap_requests = []
if "audit" not in st.session_state:
    st.session_state.audit = []
if "notifications" not in st.session_state:
    st.session_state.notifications = []

# ---------------- Load roster ----------------
st.sidebar.title("CSSA Swap — Final (Google Sheet)")
if st.sidebar.button("Load roster from Google Sheet"):
    try:
        df_try = pd.read_csv(GSHEET_CSV, dtype=str)
        df_try.columns = [c.strip() for c in df_try.columns]
        date_cols = detect_date_columns(df_try)
        if not date_cols:
            df_try2 = pd.read_csv(GSHEET_CSV, header=1, dtype=str)
            df_try2.columns = [c.strip() for c in df_try2.columns]
            dc2 = detect_date_columns(df_try2)
            if dc2:
                df_try = df_try2
                date_cols = dc2
        if not date_cols:
            st.sidebar.error("Failed to detect date columns automatically. Please check sheet formatting.")
            st.session_state.df = df_try
            st.session_state.date_cols = []
            st.session_state.debug_notes = ["Loaded but no date columns detected."]
        else:
            st.session_state.df = df_try
            st.session_state.date_cols = date_cols
            dm = {}
            for c in sorted(date_cols, key=lambda c: parse_special_date_header(c) or date.max):
                label = label_for(c)
                key = label
                k = 1
                while key in dm:
                    key = f"{label} ({k})"; k += 1
                dm[key] = c
            st.session_state.display_map = dm
            st.sidebar.success("Roster loaded and date columns detected.")
    except Exception as e:
        st.sidebar.error(f"Failed to load sheet: {e}")

if st.session_state.df is None:
    st.info("No roster loaded yet. In the sidebar click 'Load roster from Google Sheet'.")
    st.stop()

df = st.session_state.df
date_cols = st.session_state.date_cols
display_map = st.session_state.display_map
sorted_date_cols = sorted(date_cols, key=lambda c: parse_special_date_header(c) or date.max)
# Ensure display_map follows chronological order
if display_map:
    dm = {}
    for c in sorted_date_cols:
        label = label_for(c)
        key = label
        k = 1
        while key in dm:
            key = f"{label} ({k})"; k += 1
        dm[key] = c
    display_map = dm
    st.session_state.display_map = dm
    st.session_state.sorted_date_cols = sorted_date_cols

# ---------------- Build users ----------------
name_col = COL_NAME if COL_NAME in df.columns else next((c for c in df.columns if str(c).strip().lower().startswith("name")), df.columns[0])
if not st.session_state.users:
    for i in range(len(df)):
        uname = make_username(df.at[i, name_col])
        base = uname; k = 1
        while uname in st.session_state.users:
            uname = f"{base}{k}"; k += 1
        st.session_state.users[uname] = df.at[i, name_col]

# ---------------- Login ----------------
st.sidebar.subheader("Login (testing)")
usernames = list(st.session_state.users.keys())
if st.session_state.logged_user is None:
    sel = st.sidebar.selectbox("Select username", options=usernames)
    if st.sidebar.button("Login"):
        st.session_state.logged_user = sel
        st.rerun()
    st.stop()
else:
    st.sidebar.write("Logged in as:", st.session_state.users[st.session_state.logged_user])
    if st.sidebar.button("Switch User"):
        st.session_state.logged_user = None
        st.rerun()

current_user = st.session_state.users[st.session_state.logged_user]
current_idx = next((i for i in range(len(df)) if str(df.at[i, name_col]).strip() == str(current_user).strip()), 0)

# ---------------- UI Tabs ----------------
tabs = st.tabs(["Dashboard","Request Swap","Admin","Notifications","Debug"])

with tabs[0]:
    st.header(f"Welcome, {current_user}")
    st.subheader("Next 14 calendar days (horizontal)")
    today = date.today()
    days = [today + timedelta(days=i) for i in range(14)]
    cols = st.columns(14)
    for i, d in enumerate(days):
        found = None
        for rc in sorted_date_cols:
            parsed = parse_special_date_header(rc)
            if parsed == d:
                found = rc; break
        code = ""
        if found:
            try:
                code = "" if pd.isna(df.at[current_idx, found]) else str(df.at[current_idx, found]).strip()
            except Exception:
                code = ""
        with cols[i]:
            st.markdown(f"**{d.day} {d.strftime('%b')}**")
            st.markdown(f"### {code}")

    st.markdown("---")
    st.subheader("Recent swap activity")
    recent = st.session_state.swap_requests[-10:][::-1]
    if recent:
        st.table(pd.DataFrame(recent)[["id","requester","partner","date_from","date_to","status"]])
    else:
        st.write("No swap activity yet.")

with tabs[1]:
    st.header("Request a Swap")
    requester = current_user
    requester_row = current_idx

    left, right = st.columns(2)
    with left:
        st.subheader("Your shift (give away)")
        if not display_map:
            st.error("No date columns detected.")
        pick_label = st.selectbox("Your date", options=list(display_map.keys()))
        pick_col = display_map[pick_label]
        pick_idx = sorted_date_cols.index(pick_col)
        my_code = "" if pd.isna(df.at[requester_row, pick_col]) else str(df.at[requester_row, pick_col]).strip()
        st.write("Your code:", my_code)
    with right:
        st.subheader("Partner (same date auto)")
        partner_name = st.selectbox("Partner", options=[n for n in list(df[name_col].astype(str)) if n != requester], index=0)
        partner_row = df.index[df[name_col] == partner_name][0]
        partner_code = "" if pd.isna(df.at[partner_row, pick_col]) else str(df.at[partner_row, pick_col]).strip()
        if partner_code == "":
            st.warning("Partner has no shift on that date.")
        else:
            st.write("Partner code:", partner_code)

    st.markdown("---")
    st.subheader("Payback (required)")
    pay_label = st.selectbox("Payback date", options=list(display_map.keys()), index=min(2, max(0, len(display_map)-1)))
    pay_col = display_map[pay_label]
    my_pay = "" if pd.isna(df.at[requester_row, pay_col]) else str(df.at[requester_row, pay_col]).strip()
    partner_pay = "" if pd.isna(df.at[partner_row, pay_col]) else str(df.at[partner_row, pay_col]).strip()
    st.write("Your code on payback:", my_pay)
    st.write(f"{partner_name}'s code on payback:", partner_pay)

    if st.button("Submit swap request"):
        if requester == partner_name:
            st.error("Cannot swap with yourself.")
        else:
            reasons = validate_swap(df, requester_row, pick_idx, partner_row, pick_idx, sorted_date_cols, st.session_state.inexperienced)
            code_a = "" if pd.isna(df.at[requester_row, pick_col]) else str(df.at[requester_row, pick_col]).strip()
            code_b = "" if pd.isna(df.at[partner_row, pick_col]) else str(df.at[partner_row, pick_col]).strip()
            special = not (code_a.upper() in ALLOWED_AUTO_CODES and code_b.upper() in ALLOWED_AUTO_CODES)
            if reasons:
                st.error("Swap auto-declined for reasons:")
                for r in reasons:
                    st.write("- " + r)
                status = "AutoDeclined"
            elif special:
                st.info("Swap submitted (awaiting supervisor approval).")
                status = "PendingApproval"
            else:
                df.at[requester_row, pick_col], df.at[partner_row, pick_col] = code_b, code_a
                st.success("Swap auto-approved and applied (in-memory).")
                status = "AutoApproved"
            req = {"id": len(st.session_state.swap_requests) + 1, "requester": requester, "partner": partner_name, "date_from": pick_label, "date_to": pay_label, "status": status, "reasons": reasons if reasons else []}
            st.session_state.swap_requests.append(req)
            st.session_state.audit.append({"action": "REQUEST_CREATED", "request": req, "time": datetime.utcnow().isoformat()})
            if status == "AutoApproved":
                st.session_state.notifications.append({"to": [requester, partner_name], "msg": "Your swap was auto-approved."})

with tabs[2]:
    st.header("Admin Panel")
    st.subheader("Controls")
    st.write("You (app tester) are admin by default.")
    view = st.radio("View:", ["Pending Approvals", "Auto-Declined", "Override", "History", "Users & Roles"])
    if view == "Pending Approvals":
        pend = [r for r in st.session_state.swap_requests if r["status"] == "PendingApproval"]
        if not pend:
            st.info("No pending approvals.")
        else:
            for p in pend:
                st.write(p)
                c1, c2 = st.columns(2)
                if c1.button("Approve", key=f"approve_{p['id']}"):
                    col = display_map[p["date_from"]]
                    rr = df.index[df[name_col] == p["requester"]][0]
                    pr = df.index[df[name_col] == p["partner"]][0]
                    df.at[rr, col], df.at[pr, col] = df.at[pr, col], df.at[rr, col]
                    p["status"] = "SupervisorApproved"
                    st.success(f"Request {p['id']} approved.")
                    st.session_state.notifications.append({"to": [p["requester"], p["partner"]], "msg": "Supervisor approved your swap."})
    elif view == "Auto-Declined":
        auto = [r for r in st.session_state.swap_requests if r["status"] == "AutoDeclined"]
        if not auto:
            st.info("No auto-declined requests.")
        else:
            for a in auto:
                st.write(a)
    elif view == "Override":
        dec = [r for r in st.session_state.swap_requests if r["status"] in ("AutoDeclined", "SupervisorDeclined")]
        if not dec:
            st.info("No declined requests.")
        else:
            for d in dec:
                st.write(d)
                if st.button("Override & Approve", key=f"ovr_{d['id']}"):
                    col = display_map[d["date_from"]]
                    rr = df.index[df[name_col] == d["requester"]][0]
                    pr = df.index[df[name_col] == d["partner"]][0]
                    df.at[rr, col], df.at[pr, col] = df.at[pr, col], df.at[rr, col]
                    d["status"] = "OverriddenApproved"
                    st.success("Overridden & approved.")
    elif view == "History":
        hist = st.session_state.audit[::-1]
        if not hist:
            st.info("No history yet.")
        else:
            for h in hist[:200]:
                st.write(h)
    elif view == "Users & Roles":
        names = list(df[name_col].astype(str))
        sel = st.multiselect("Mark inexperienced controllers", options=names, default=list(st.session_state.inexperienced))
        st.session_state.inexperienced = set(sel)
        st.write("Inexperienced:", st.session_state.inexperienced)
        if st.button("Download updated roster (.xlsx)"):
            st.download_button("Download roster", data=df_to_excel_bytes(df), file_name="updated_roster.xlsx")

with tabs[3]:
    st.header("Notifications (simulated)")
    if st.session_state.notifications:
        for n in st.session_state.notifications[::-1]:
            st.write(f"To: {', '.join(n['to'])} — {n['msg']}")
    else:
        st.write("No notifications yet.")

with tabs[4]:
    st.header("Debug")
    st.subheader("Notes")
    st.write(st.session_state.get("debug_notes", "No notes"))
    st.subheader("Columns (raw)")
    st.write(list(df.columns))
    st.subheader("Detected date columns")
    st.write(date_cols)
    st.subheader("Display map (label -> col key)")
    st.write(display_map)
    st.subheader("First 8 rows")
    st.write(df.head(8))

# footer
st.sidebar.markdown("---")
st.sidebar.write("This app reads your Google Sheet. To enable writeback later, add a GCP service account JSON to Streamlit secrets under 'gcp_service_account'.")
