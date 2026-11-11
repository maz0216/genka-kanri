from contextlib import closing

import pandas as pd
import psycopg2
import streamlit as st

# 表示用の列順（CLAUDE.mdの仕様どおり）
DISPLAY_COLUMNS = ["工番", "分番", "組番", "実績額", "着地見込み", "予算額", "コメント"]

# 役割ごとにできること。権限の対応はここ1か所だけで決める
#   view：表を見る / comment：コメントを書く / import：CSVを取り込む
PERMISSIONS = {
    "viewer": {"view"},
    "editor": {"view", "comment"},
    "admin": {"view", "comment", "import"},
}


def can(role, action):
    """その役割がその操作をしてよいか。知らない役割（None含む）は何もできない。"""
    return action in PERMISSIONS.get(role, set())


def calc_mikomi(jisseki):
    """着地見込みの計算ルール。ここ1か所だけ直せば計算方法を変えられる。"""
    return jisseki * 1.5


def get_connection():
    # 接続文字列はst.secretsからのみ読む。コードに直接書かない
    return psycopg2.connect(st.secrets["DATABASE_URL"])


def get_role(email):
    """app_usersからその人の役割を読む（読むだけ）。登録がなければNone。"""
    if not email:
        return None
    with closing(get_connection()) as conn:
        with conn.cursor() as cur:
            # app_usersは小文字で登録されているので、こちらも小文字にそろえて比べる
            cur.execute(
                "SELECT role FROM app_users WHERE email = %s",
                (email.strip().lower(),),
            )
            row = cur.fetchone()
    return row[0] if row else None


def read_csv_as_str_keys(uploaded_file, amount_column):
    # 工番・分番・組番は先頭ゼロを落とさないよう文字列として読む
    df = pd.read_csv(
        uploaded_file,
        dtype={"工番": str, "分番": str, "組番": str},
    )
    required_columns = ["工番", "分番", "組番", amount_column]
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        st.error(
            f"CSVに必要な列が見つかりません：{', '.join(missing)}。"
            "ファイルを選び間違えていないか確認してください。"
        )
        return None
    df[amount_column] = pd.to_numeric(df[amount_column])
    return df


def upsert_budget(df):
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            for _, row in df.iterrows():
                cur.execute(
                    """
                    INSERT INTO genka (kouban, bunban, kumiban, yosan)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (kouban, bunban, kumiban)
                    DO UPDATE SET yosan = excluded.yosan
                    """,
                    (row["工番"], row["分番"], row["組番"], row["予算額"]),
                )


def upsert_actual(df):
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            for _, row in df.iterrows():
                cur.execute(
                    """
                    INSERT INTO genka (kouban, bunban, kumiban, jisseki)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (kouban, bunban, kumiban)
                    DO UPDATE SET jisseki = excluded.jisseki
                    """,
                    (row["工番"], row["分番"], row["組番"], row["実績額"]),
                )


def load_all():
    with closing(get_connection()) as conn:
        df = pd.read_sql_query(
            "SELECT * FROM genka ORDER BY kouban, bunban, kumiban", conn
        )
    df = df.rename(
        columns={
            "kouban": "工番",
            "bunban": "分番",
            "kumiban": "組番",
            "jisseki": "実績額",
            "yosan": "予算額",
            "comment": "コメント",
        }
    )
    # jisseki/yosanはPostgresのNUMERIC型なのでDecimalとして返ってくる。計算できるようfloatにする
    df["実績額"] = pd.to_numeric(df["実績額"])
    df["予算額"] = pd.to_numeric(df["予算額"])
    df["着地見込み"] = df["実績額"].apply(calc_mikomi)
    return df[DISPLAY_COLUMNS]


def save_comments(edited_df):
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            for _, row in edited_df.iterrows():
                cur.execute(
                    """
                    UPDATE genka SET comment = %s
                    WHERE kouban = %s AND bunban = %s AND kumiban = %s
                    """,
                    (row["コメント"], row["工番"], row["分番"], row["組番"]),
                )


st.set_page_config(page_title="原価管理（段階3）", layout="wide")
st.title("原価管理アプリ（段階3・ログイン版）")

# --- 認証：ログインしていない人には、ログインボタンだけを見せて止める ---
if not st.user.is_logged_in:
    st.write("このアプリを使うには、Googleアカウントでログインしてください。")
    st.button("Googleでログイン", on_click=st.login)
    st.stop()  # ここで処理終了。下の表やアップロード欄（DB接続も）は実行されない

# --- 認可：app_usersで役割を調べる。画面が動くたびに読み直す ---
role = get_role(st.user.email)
if not can(role, "view"):
    # 表に載っていない人・想定外の役割の人。表は見せずに止める
    st.error("権限がありません")
    st.button("ログアウト", on_click=st.logout)
    st.stop()

# --- ログイン中：自分のメールアドレス・役割とログアウトボタン ---
user_col, logout_col = st.columns([4, 1])
with user_col:
    st.write(f"ログイン中：{st.user.email}（役割：{role}）")
with logout_col:
    st.button("ログアウト", on_click=st.logout)


def require(action):
    """処理の直前に役割を確かめる。権限がなければDBに触らずにここで止める。"""
    if not can(role, action):
        st.error("この操作を行う権限がありません。")
        st.stop()


# --- CSV取り込み：importできる人にだけ出す ---
if can(role, "import"):
    col1, col2 = st.columns(2)

    with col1:
        budget_file = st.file_uploader("予算CSVをアップロード", type="csv", key="budget")
        if budget_file is not None:
            budget_df = read_csv_as_str_keys(budget_file, "予算額")
            if budget_df is not None:
                require("import")  # 書き込む直前にもう一度確認
                upsert_budget(budget_df)
                st.success(f"予算を{len(budget_df)}行取り込みました。")

    with col2:
        actual_file = st.file_uploader("実績CSVをアップロード", type="csv", key="actual")
        if actual_file is not None:
            actual_df = read_csv_as_str_keys(actual_file, "実績額")
            if actual_df is not None:
                require("import")  # 書き込む直前にもう一度確認
                upsert_actual(actual_df)
                st.success(f"実績を{len(actual_df)}行取り込みました。")

    st.divider()

data = load_all()

can_comment = can(role, "comment")

edited = st.data_editor(
    data,
    column_config={
        "工番": st.column_config.TextColumn(disabled=True),
        "分番": st.column_config.TextColumn(disabled=True),
        "組番": st.column_config.TextColumn(disabled=True),
        "実績額": st.column_config.NumberColumn(disabled=True, format="%d"),
        "着地見込み": st.column_config.NumberColumn(disabled=True, format="%.1f"),
        "予算額": st.column_config.NumberColumn(disabled=True, format="%d"),
        # コメントを書けない役割では、コメント列も入力できないようにする
        "コメント": st.column_config.TextColumn(disabled=not can_comment),
    },
    hide_index=True,
    use_container_width=True,
    key="editor",
)

if can_comment:
    if st.button("コメントを保存"):
        require("comment")  # 保存する直前にもう一度確認
        save_comments(edited)
        st.success("コメントを保存しました。")
        st.rerun()
