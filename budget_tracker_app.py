import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from datetime import datetime

DB = "budget.db"


def hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)


def ensure_schema():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT
            )"""
    )
    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO users(username, password) VALUES(?,?)",
            ("admin", hash_pwd("admin")),
        )

    cur.execute(
        """CREATE TABLE IF NOT EXISTS transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                category TEXT,
                amount REAL
            )"""
    )

    cols = [c[1] for c in cur.execute("PRAGMA table_info(transactions)")]
    if "user_id" not in cols:
        cur.execute("ALTER TABLE transactions ADD COLUMN user_id INTEGER")
        cur.execute("UPDATE transactions SET user_id = 1 WHERE user_id IS NULL")

    conn.commit()


def authenticate(username: str, password: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT id, password FROM users WHERE username=?", (username,)
    ).fetchone()
    if row and row[1] == hash_pwd(password):
        return row[0]
    return None


def get_username(user_id: int) -> str:
    conn = get_conn()
    row = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    return row[0] if row else "unknown"


def change_password(user_id: int, new_pwd: str):
    conn = get_conn()
    conn.execute("UPDATE users SET password=? WHERE id=?", (hash_pwd(new_pwd), user_id))
    conn.commit()


def create_user(username: str, password: str) -> bool:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users(username, password) VALUES(?,?)",
            (username, hash_pwd(password)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def add_tx(date: datetime.date, category: str, amount: float):
    conn = get_conn()
    conn.execute(
        "INSERT INTO transactions(date, category, amount, user_id) VALUES(?,?,?,?)",
        (date.isoformat(), category, amount, st.session_state.user_id),
    )
    conn.commit()


def fetch_tx() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY date",
        conn,
        params=(st.session_state.user_id,),
    )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df["Month"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
    return df


def delete_tx(tx_id: int):
    conn = get_conn()
    conn.execute(
        "DELETE FROM transactions WHERE id=? AND user_id=?",
        (tx_id, st.session_state.user_id),
    )
    conn.commit()


def login_ui():
    st.title("💰 Personal Budget Tracker – Login")
    st.caption("Default credentials → **admin / admin** (change after login)")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        user_id = authenticate(username, password)
        if user_id:
            st.session_state.auth = True
            st.session_state.user_id = user_id
            st.session_state.username = username
            try:
                st.experimental_rerun()
            except AttributeError:
                st.rerun()
        else:
            st.error("Invalid credentials. Try again.")


def account_settings_ui():
    st.header("👤 Account Settings")

    with st.expander("Change Password"):
        pwd1 = st.text_input("New password", type="password", key="cp1")
        pwd2 = st.text_input("Repeat new password", type="password", key="cp2")
        if st.button("Update password", key="cpbtn"):
            if pwd1 and pwd1 == pwd2:
                change_password(st.session_state.user_id, pwd1)
                st.success("Password updated ✔️")
            else:
                st.error("Passwords don't match or empty.")

    with st.expander("Add New User"):
        new_user = st.text_input("Username", key="nu1")
        new_pwd1 = st.text_input("Password", type="password", key="nu2")
        new_pwd2 = st.text_input("Repeat password", type="password", key="nu3")
        if st.button("Create user", key="nu_btn"):
            if new_user and new_pwd1 == new_pwd2:
                if create_user(new_user, new_pwd1):
                    st.success(f"User '{new_user}' created ✔️")
                else:
                    st.error("Username already exists.")
            else:
                st.error("Fill all fields and ensure passwords match.")

    if st.button("Logout ⚡", type="secondary"):
        for key in ["auth", "user_id", "username"]:
            st.session_state.pop(key, None)
        try:
            st.experimental_rerun()
        except AttributeError:
            st.rerun()


def budget_ui():
    st.sidebar.success(f"Logged in as {st.session_state.username}")

    with st.sidebar.expander("⚙️ Settings / Account"):
        st.button("Open settings panel", on_click=lambda: st.session_state.update(show_settings=True), use_container_width=True)

    if st.session_state.get("show_settings", False):
        account_settings_ui()
        st.divider()

    st.title("💸 Personal Budget Tracker")
    st.write("Log your income and expenses, and track monthly savings.")

    with st.sidebar:
        st.header("Add Transaction")
        date = st.date_input("Date", datetime.today())
        category = st.text_input("Category")
        amount = st.number_input(
            "Amount (₸) — positive = income, negative = expense",
            step=100.0,
            format="%.2f",
        )
        if st.button("Add", type="primary", use_container_width=True):
            if category and amount != 0:
                add_tx(date, category, amount)
                try:
                    st.experimental_rerun()
                except AttributeError:
                    st.rerun()
            else:
                st.warning("Enter a category and non‑zero amount.")

    df = fetch_tx()
    if df.empty:
        st.info("No transactions yet. Use the sidebar to add your first one!")
        return

    month_totals = df.groupby("Month")["amount"].sum().reset_index()
    current_month = month_totals.iloc[-1]
    st.metric("Current Month Savings (₸)", f"{current_month['amount']:.0f}")

    st.bar_chart(month_totals.set_index("Month"))

    st.subheader("All Transactions")
    for _, row in df.iterrows():
        cols = st.columns([2, 3, 2, 1])
        cols[0].write(row["date"])
        cols[1].write(row["category"])
        cols[2].write(f"{row['amount']:.0f}")
        if cols[3].button("🗑️", key=f"del{row['id']}"):
            delete_tx(row["id"])
            try:
                st.experimental_rerun()
            except AttributeError:
                st.rerun()


def main():
    st.set_page_config(page_title="Budget Tracker", page_icon="💰", layout="wide")
    ensure_schema()

    if not st.session_state.get("auth", False):
        login_ui()
    else:
        budget_ui()

if __name__ == "__main__":
    main()
