# -*- coding: utf-8 -*-
from flask import Flask, request, session, redirect, url_for, render_template, jsonify
from flask_session import Session
import pyodbc
from datetime import datetime
from functools import wraps
import logging
import requests
import json
import msal
import os
from werkzeug.middleware.proxy_fix import ProxyFix
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_env_setting(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# Setup detailed logging to file and console before app creation
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[
        logging.FileHandler("/tmp/app_api_calls.log"),
        logging.StreamHandler()
    ]
)


app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = get_env_setting("FLASK_SECRET_KEY", default="local-dev-secret-key")
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

SESSION_KEY = "user"


# Azure Configuration
CLIENT_ID = get_env_setting("AZURE_CLIENT_ID", default="37450a1d-d9c8-4cd9-8093-58f60d329749")
CLIENT_SECRET = get_env_setting("AZURE_CLIENT_SECRET", required=True)
TENANT_ID = get_env_setting("AZURE_TENANT_ID", default="d283f563-83f4-4d65-a9d1-028758bd1572")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_URI = "https://asksparkqa/"
SCOPE = ["User.Read"]


# Database connection string - secure in production via env variables
DB_DRIVER = get_env_setting("DB_DRIVER", default="ODBC Driver 17 for SQL Server")
DB_SERVER = get_env_setting("DB_SERVER", default="sql-product")
DB_NAME = get_env_setting("DB_NAME", default="SOG_Chatbot")
DB_USER = get_env_setting("DB_USER", default="na_proxy")
DB_PASSWORD = get_env_setting("DB_PASSWORD", required=True)
DB_CONNECTION_TIMEOUT = get_env_setting("DB_CONNECTION_TIMEOUT", default="60")

CONN_STR = (
    f"Driver={{{DB_DRIVER}}};"
    f"Server={DB_SERVER};"
    f"Database={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
    f"Connection Timeout={DB_CONNECTION_TIMEOUT};"
)

#DATABRICKS_URL = "https://adb-2499533172944623.3.azuredatabricks.net/serving-endpoints/agents_dev-featurestoretest-jarvis_rag_langgraph_agent_OpenAI/invocations"
DATABRICKS_URL = "https://adb-2499533172944623.3.azuredatabricks.net/serving-endpoints/agents_dev-featurestoretest-spark_agent_OpenAI/invocations"
#DATABRICKS_URL = "https://adb-2499533172944623.3.azuredatabricks.net/serving-endpoints/agents_dev-featurestoretest-spark_agent_OpenAI_UAT/invocations"
API_TOKEN = get_env_setting("DATABRICKS_API_TOKEN", required=True)

try:
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cursor = conn.cursor()
    logging.info("Database connected successfully")
except Exception as e:
    logging.error(f"Database connection error: {e}")
    raise

def get_logged_in_user():
    user = session.get(SESSION_KEY, {})
    return (
        user.get("preferred_username")
        or user.get("upn")
        or user.get("email")
        or "Unknown"
    )


def build_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )

def save_session(session_id):
    try:
        cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM TCC_sessions_uat WHERE session_id=?)
            INSERT INTO TCC_sessions_uat (session_id, start_time) VALUES (?, ?)
        """, (session_id, session_id, datetime.utcnow()))
    except Exception as e:
        logging.error(f"Error saving session {session_id}: {e}")


def save_message(session_id, sender, message):
    try:
        if sender.lower() == "user":
            sender = get_logged_in_user()
        cursor.execute("""
            INSERT INTO TCC_chat_logs_uat (session_id, sender, message, timestamp)
            VALUES (?, ?, ?, ?)
        """, (session_id, sender, message, datetime.utcnow()))
    except Exception as e:
        logging.error(f"Error saving message for session {session_id}: {e}")


def save_tool_run(session_id, tool_name, account_number, company, result):
    try:
        run_by = get_logged_in_user()
        if isinstance(result, (dict, list)):
            result = json.dumps(result)
        cursor.execute("""
            INSERT INTO TCC_tool_runs_uat
                (session_id, tool_name, account_number, company, run_by, result, run_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session_id, tool_name, account_number, company, run_by, result, datetime.utcnow()))
    except Exception as e:
        logging.error(f"Error saving tool run for session {session_id}: {e}")


def get_chat_history(session_id):
    try:
        cursor.execute("""
            SELECT sender, message, timestamp FROM TCC_chat_logs_uat
            WHERE session_id=?
            ORDER BY timestamp
        """, (session_id,))
        return cursor.fetchall()
    except Exception as e:
        logging.error(f"Error fetching chat history for session {session_id}: {e}")
        return []


def get_top3_history(history):
    filtered = [
        {"role": r.sender.lower(), "content": r.message}
        for r in history
        if r.sender.lower() in ("user", "assistant")
    ]
    return filtered[-3:]


def call_agent(user_message, session_id, history):
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        formatted_history = get_top3_history(history)
       # messages = [{"role": "user", "content": user_message.strip()}]
        current_msg = {"role": "user", "content": user_message.strip()}
        messages = formatted_history + [current_msg]

        payload = {
            "messages": messages,
            #"history": formatted_history,
            "context": {
                "conversation_id": session_id,
                "user_id":  get_logged_in_user()
            },
            "custom_inputs": {},
            "stream": False
        }

        logging.info(f"Sending Databricks request for session {session_id}:\n{payload}")

        response = requests.post(DATABRICKS_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()

        logging.info(f"Received Databricks response for session {session_id}:\n{data}")

        assistant_reply = None
        if isinstance(data, dict) and "messages" in data:
            for msg in data["messages"]:
                if msg.get("role") == "assistant":
                    assistant_reply = msg.get("content", "No response content found.")
                    break

        databricks_request_id = None
        if isinstance(data, dict):
            databricks_output = data.get("databricks_output", {})
            databricks_request_id = databricks_output.get("databricks_request_id")

        return assistant_reply, databricks_request_id

    except requests.exceptions.RequestException as e:
        logging.error(f"Databricks API error for session {session_id}: {e} | Response: {getattr(e.response, 'text', 'No response text')}")
        return "Error: assistant service unavailable.", None
    except Exception as e:
        logging.error(f"Unexpected error in call_agent for session {session_id}: {e}")
        return "Error: assistant unavailable.", None

def get_requested_item_details(sysparm_search, username, password):
    """
    Fetch ServiceNow records for all relevant labels and return details with comments.

    Args:
        sysparm_search (str): Search term (usually account number)
        username (str): ServiceNow API username
        password (str): ServiceNow API password

    Returns:
        List[dict]: List of records with ticket_number, state, opened_by, requested_for, opened_at,
                    assignment_group, record_url, and comments
    """
    #search_url = "https://cabodev.service-now.com/api/now/globalsearch/search"
    search_url = "https://caboproduction.service-now.com/api/now/globalsearch/search"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    # Step 1: Global Search API
    params = {"sysparm_search": sysparm_search, "sysparm_groups": "9aff3b96c33b3a50973924f9d0013192"}
    response = requests.get(search_url, params=params, auth=(username, password), headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()

    #base_url = "https://cabodev.service-now.com"
    base_url = "https://caboproduction.service-now.com"
    results = []

    # Step 2: Map assignment groups from Catalog Tasks
    assignment_map = {}  # key: request_item sys_id, value: assignment_group display
    for group in data.get("result", {}).get("groups", []):
        for search_result in group.get("search_results", []):
            if search_result.get("label") == "Catalog Task":
                for record in search_result.get("records", []):
                    record_data = record.get("data", {})
                    assignment_group_display = record_data.get("assignment_group", {}).get("display") \
                                               or record_data.get("assignment_group", {}).get("value")
                    request_item_sys_id = record_data.get("request_item", {}).get("value")
                    if request_item_sys_id and assignment_group_display:
                        assignment_map[request_item_sys_id] = assignment_group_display

    # Step 3: Label ? Table API mapping
    label_map = {
        "Incident": "incident",
        "Change Request": "change_request",
        "Change Task": "change_task",
        "Problem": "problem",
        "Request": "sc_request",
        "Catalog Task": "sc_task",
        "Requested Item": "sc_req_item"
    }

    # Step 4: Iterate through all labels
    for group in data.get("result", {}).get("groups", []):
        for search_result in group.get("search_results", []):
            label = search_result.get("label")
            
            allowed_labels = {
                "Incident",
                "Change Request",
                "Change Task",
                "Problem",
                "Request",
                "Catalog Task",
                "Requested Item"
            }

            if label not in allowed_labels:
                continue
            records = search_result.get("records", [])
            if not records:
                continue  # skip empty records

            # Sort by opened_at descending
            records_sorted = sorted(
                records,
                key=lambda r: r.get("data", {}).get("opened_at", {}).get("value") or "",
                reverse=True
            )
            record = records_sorted[0]  # most recent
            record_data = record.get("data", {})

            # Extract all fields with proper fallbacks
            sys_id = record_data.get("sys_id", {}).get("value") or record.get("sys_id")
            number = (
                record_data.get("number", {}).get("display") 
                or record_data.get("number", {}).get("value") 
                or record_data.get("number")
                or "N/A"
            )
            state = (
                record_data.get("state", {}).get("display") 
                or record_data.get("state", {}).get("value") 
                or "N/A"
            )
            opened_at = record_data.get("opened_at", {}).get("display") \
                        or record_data.get("opened_at", {}).get("value") \
                        or "N/A"
            opened_by = record_data.get("opened_by", {}).get("display") \
                        or record_data.get("opened_by", {}).get("value") \
                        or record_data.get("caller_id", {}).get("display")\
                        or "N/A"
            requested_for = record_data.get("requested_for", {}).get("display") \
                            or record_data.get("requested_for", {}).get("value") \
                            or record_data.get("caller_id", {}).get("display")\
                            or "N/A"
            assignment_group = assignment_map.get(sys_id) \
                               or record_data.get("assignment_group", {}).get("display") \
                               or record_data.get("assignment_group", {}).get("value") \
                               or "N/A"
            record_url = f'{base_url}{record.get("record_url")}' if record.get("record_url") else "N/A"

            # Step 5: Fetch most recent comment from Table API
            table_name = label_map.get(label)
            comments = "No comments"
            if sys_id:
                comments_url = f"{base_url}/api/now/table/sys_journal_field"
                comments_params = {
                    "sysparm_query": f"element_id={sys_id}^element=comments",
                    "sysparm_display_value": "true",
                    "sysparm_fields": "value,sys_created_on",
                    "sysparm_limit": 2,
                    "sysparm_order_by_desc": "sys_created_on"
                }
            
                try:
                    comments_resp = requests.get(
                        comments_url,
                        params=comments_params,
                        auth=(username, password),
                        headers=headers,
                        timeout=30
                    )
                    comments_resp.raise_for_status()
                    comments_data = comments_resp.json()
            
                    if comments_data.get("result"):
                        comments_list = [
                            f"{c.get('sys_created_on')} - {c.get('value')}"
                            for c in comments_data["result"]
                        ]
                        comments = "\n\n".join(comments_list)
                    else:
                        comments = "No comments"
            
                except Exception as e:
                    logging.warning(f"Failed to fetch comments for {number}: {e}")
                    comments = "Error fetching comments"

            result = {
                "label": label,
                "ticket_number": number,
                "state": state,
                "opened_at": opened_at,
                "opened_by": opened_by,
                "requested_for": requested_for,
                "assignment_group": assignment_group,
                "record_url": record_url,
                "comments": comments
            }

            logging.info(result)
            results.append(result)

    return results
    

# =================================================
# HEADERS
# =================================================

ACCOUNT_HEADERS = {
    "client_id": "Automation_acp_middleware_account",
    "client_secret": get_env_setting("ACCOUNT_API_CLIENT_SECRET", required=True),
    "Content-Type": "application/json",
}

SYSTEM_HEADERS = {
    "client_id": "Automation_c1_system_information_sapi",
    "client_secret": get_env_setting("SYSTEM_API_CLIENT_SECRET", required=True),
    "Content-Type": "application/json",
}

OUTAGE_HEADERS = {
    "client_id": "Automation_c1_outage_now_sapi",
    "client_secret": get_env_setting("OUTAGE_API_CLIENT_SECRET", required=True),
    "Content-Type": "application/json",
}

BASE_SYSTEM_URL = (
    "http://gateway-internal-apisix.apps.prod-ocp4.corp.cableone.net"
    "/c1-system-information-sapi/api/v1"
)

# =================================================
# SAFE CALL
# =================================================

def _safe_call(label, fn, *args):
    try:
        return label, fn(*args)
    except Exception as e:
        logging.error(f"{label} failed: {e}")
        return label, None
        
def safe_get(obj, key, default=None):
    """
    Safely get a key from a dict; returns default if obj is not a dict.
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default

# =================================================
# LOOKUPS
# =================================================

def get_business_unit(account_number):
    """
    Fetches account data from the API and returns the business_unit string.

    Raises:
        requests.HTTPError if the API call fails
        ValueError if business_unit is not found
    """
    url = (
        "http://gateway-internal-apisix.apps.prod-ocp4.corp.cableone.net"
        f"/acp-middleware-account/accounts/{account_number}"
    )
    r = requests.get(url, headers=ACCOUNT_HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()

    business_unit = data.get("business_unit")
    if not business_unit:
        raise ValueError(f"Business unit not found for account {account_number}")

    return business_unit

def get_system_info(business_unit):
    url = f"{BASE_SYSTEM_URL}/systems/filter"
    r = requests.get(url, headers=SYSTEM_HEADERS, params={"spa": business_unit}, timeout=10)
    r.raise_for_status()
    return r.json()

# =================================================
# SYSTEM DATA
# =================================================

def get_office_hours(system_id):
    url = f"{BASE_SYSTEM_URL}/systems/{system_id}/office/hours"
    r = requests.get(url, headers=SYSTEM_HEADERS, params={"dayStart": 1, "dayEnd": 7, "hourtype" : 1}, timeout=10)
    r.raise_for_status()
    return r.json()

def get_system_edit_details(system_id):
    url = f"{BASE_SYSTEM_URL}/systems/{system_id}/edit-details"
    r = requests.get(url, headers=SYSTEM_HEADERS, timeout=10, verify=False)
    r.raise_for_status()
    return r.json()

def get_equipment_details(system_id):
    url = f"{BASE_SYSTEM_URL}/systems/{system_id}/equipment"
    r = requests.get(url, headers=SYSTEM_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

def get_service_info(system_id):
    url = f"{BASE_SYSTEM_URL}/systems/{system_id}/service-info"
    r = requests.get(url, headers=SYSTEM_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

def get_service_areas(system_id):
    url = f"{BASE_SYSTEM_URL}/systems/{system_id}/service-areas"
    r = requests.get(url, headers=SYSTEM_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

def get_equipment_return_boxes(system_id):
    url = f"{BASE_SYSTEM_URL}/systems/{system_id}/equipment-return-boxes"
    r = requests.get(url, headers=SYSTEM_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

def get_office_alerts(system_id):
    url = f"{BASE_SYSTEM_URL}/systems/{system_id}/office/alerts"
    r = requests.get(url, headers=SYSTEM_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()
    

def get_drop_bury_info(system_id):
    url = f"http://gateway-internal-apisix.apps.prod-ocp4.corp.cableone.net/c1-system-information-sapi/api/v1/systems/{system_id}/drop-bury"
    r = requests.get(url, headers=SYSTEM_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()



# -------- GET ACTIVE OUTAGES --------

def get_active_outages_for_system(system_name):
    url = (
        "http://gateway-internal-apisix.apps.prod-ocp4.corp.cableone.net"
        "/c1-outage-now-sapi/api/v1/outages"
    )

    params = [
        ("Statuses", "Declared"),
        ("Statuses", "Assigned"),
        ("Statuses", "InRoute"),
        ("approvals", "Approved"),
        ("operatingCenters", system_name),
        ("operatingCenters", "All Systems"),
        ("pageSize", "100"),
        ("offset", "0"),
    ]

    r = requests.get(url, headers=OUTAGE_HEADERS, params=params, timeout=10)
    r.raise_for_status()
    return r.json()
    

# ---------------- RUN APPHUB TOOL ----------------
def run_apphub_tool(account_number):
    try:
        # -------- Step 1: get business unit --------
        business_unit = get_business_unit(account_number)

        systems = get_system_info(business_unit)
        if not systems:
            return "No system information found"

        system = systems[0] if isinstance(systems, list) else systems
        system_id = safe_get(system, "systemId")
        system_name = safe_get(system, "systemName", "")

        if not system_id:
            return f"System ID not found for business_unit {business_unit}"

        # -------- Step 2: fetch parallel data --------
        tasks = {
            "office_hours":           (get_office_hours, system_id),
            "edit_details":           (get_system_edit_details, system_id),
            "equipment":              (get_equipment_details, system_id),
            "drop_bury_info":         (get_drop_bury_info, system_id),  # ? correct API
            "service_areas":          (get_service_areas, system_id),
            "equipment_return_boxes": (get_equipment_return_boxes, system_id),
            "office_alerts":          (get_office_alerts, system_id),
            "outages":                (get_active_outages_for_system, system_name),
        }

        fetched = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(_safe_call, label, fn, *args): label
                for label, (fn, *args) in tasks.items()
            }
            for f in as_completed(futures):
                label, data = f.result()
                fetched[label] = data

        # -------- Step 3: normalize edit details --------
        edit_details = fetched.get("edit_details")
        if isinstance(edit_details, list) and edit_details:
            edit_details = edit_details[0] if isinstance(edit_details[0], dict) else {}
        elif not isinstance(edit_details, dict):
            edit_details = {}

        state = safe_get(edit_details, "stateProvince")

        # -------- Step 4: equipment return boxes --------
        equipment_return_boxes_raw = fetched.get("equipment_return_boxes") or []
        return_box_addresses = [
            safe_get(b, "equipmentReturnBoxAddress")
            for b in equipment_return_boxes_raw
            if isinstance(b, dict) and safe_get(b, "equipmentReturnBoxAddress")
        ]

        # -------- Step 5: ? CRITICAL FIX — pass ARRAY directly --------
        wall_fish_information = (
            fetched.get("drop_bury_info")
            if isinstance(fetched.get("drop_bury_info"), list)
            else []
        )

        # -------- Step 6: assemble final result --------
        result = {
            "business_unit": business_unit,
            "system_information": {
                "system_id": system_id,
                "system_name": system_name,
                "state": state,
                "service_area_names": safe_get(system, "serviceAreaNames"),
                "subcity_information": fetched.get("service_areas"),
                "office_hours": fetched.get("office_hours"),
                "office_alerts": fetched.get("office_alerts"),
                "edit_details": edit_details,
                "equipment": fetched.get("equipment"),
                "equipment_return_box_addresses": return_box_addresses,
                "equipment_return_boxes": fetched.get("equipment_return_boxes"),

                # ??? THIS MUST BE AN ARRAY
                "wall_fish_information": wall_fish_information,
            },
            "outage_information": fetched.get("outages") or [],
        }

        return result

    except Exception as e:
        logging.error(
            f"run_apphub_tool failed for account {account_number}: {e}",
            exc_info=True
        )
        return f"AppHub API failed: {str(e)}"
        

# =========================
# TCC MODEM SIGNAL API
# =========================
TCC_ACCOUNT_URL = "https://askspark-api-tempo-api-staging.apps.prod-ocp4.corp.cableone.net/api/Account"
TCC_MODEM_URL = "https://askspark-api-tempo-api-staging.apps.prod-ocp4.corp.cableone.net/api/Account/{account_number}/modem"


def get_tcc_account(account_number):
    url = f"{TCC_ACCOUNT_URL}/{account_number}"
    r = requests.get(url, timeout=15, verify=False)
    r.raise_for_status()
    return r.json()


def get_tcc_modem_signal(account_number):
    url = TCC_MODEM_URL.format(account_number=account_number)
    r = requests.get(url, timeout=15, verify=False)
    r.raise_for_status()
    return r.json()



def run_tcc_modem_signal_tool(account_number):
    account_data = get_tcc_account(account_number)
    modem_data = get_tcc_modem_signal(account_number)

    return {
        "billingInfo": {
            "business_unit": account_data.get("business_unit"),
            "current_balance": account_data.get("current_balance"),
            "last_payment_amount": account_data.get("last_payment_amount"),
            "last_payment_date": account_data.get("last_payment_date"),
            "payment_due_amount": account_data.get("payment_due_amount"),
            "payment_due_date": account_data.get("payment_due_date"),
            "past_due_amount": account_data.get("past_due_amount")
        },
        "modemSignalLevels": modem_data
    }


# =========================
# TCC EQUIPMENT DETAILS API
# =========================
TCC_SERVICE_URL = (
    "https://askspark-api-tempo-api-staging.apps.prod-ocp4.corp.cableone.net"
    "/api/Service/{account_number}"
)

def run_tcc_equipment_details_tool(account_number):
    """
    TCC Equipment Details Tool
    Returns modem MAC/state + equipment list
    """
    try:
        # -------- Modem API --------
        modem_resp = requests.get(
            TCC_MODEM_URL.format(account_number=account_number),
            timeout=15,
            verify=False
        )
        modem_resp.raise_for_status()
        modem_data = modem_resp.json()

        # -------- Service API (Equipment) --------
        service_resp = requests.get(
            TCC_SERVICE_URL.format(account_number=account_number),
            params={
                "IncludeEquipment": "true",
                "IncludeLocation": "true"
            },
            timeout=15,
            verify=False
        )
        service_resp.raise_for_status()
        service_data = service_resp.json()

        return {
            "account": modem_data.get("account"),
            "modemDetails": {
                "modemMAC": modem_data.get("modemMAC"),
                "modemState": modem_data.get("modemState")
            },
            "equipmentDetails": service_data.get("equipments", [])
        }

    except Exception as e:
        logging.error(
            f"TCC Equipment Details tool failed | account={account_number}",
            exc_info=True
        )
        return f"TCC Equipment Details failed: {str(e)}"


# -----------------------
# Login Required Decorator
# -----------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if SESSION_KEY not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper

# -----------------------
# Routes
# -----------------------
@app.route("/")
def root():
    code = request.args.get("code")
    if code:
        result = build_msal_app().acquire_token_by_authorization_code(
            code, scopes=SCOPE, redirect_uri=REDIRECT_URI
        )
        if "id_token_claims" in result:
            session[SESSION_KEY] = result["id_token_claims"]
            return redirect(url_for("home"))
        return "Authentication failed: " + str(result.get("error_description"))
    if SESSION_KEY in session:
        return redirect(url_for("home"))
    return render_template("login.html")

@app.route("/login")
def login_page():
    return render_template("login.html")

@app.route("/azure-login", methods=["POST"])
def azure_login():
    username = request.form.get("username")
    auth_url = build_msal_app().get_authorization_request_url(
        scopes=SCOPE, redirect_uri=REDIRECT_URI, login_hint=username
    )
    return redirect(auth_url)

@app.route("/home")
@login_required
def home():
    user = session[SESSION_KEY]
    return render_template("index.html", username=user.get("name"), email=user.get("preferred_username"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(f"{AUTHORITY}/oauth2/v2.0/logout?post_logout_redirect_uri={REDIRECT_URI}")



@app.route('/api/message', methods=['POST'])
def api_message():
    d = request.get_json()
    session_id = d.get("session_id", "default")
    msg = d.get("message", "")
    save_session(session_id)
    save_message(session_id, "User", msg)

    history = get_chat_history(session_id)

    reply, request_id = call_agent(msg, session_id, history)
    
    save_message(session_id, "Assistant", reply)

    if request_id:
        try:
            cursor.execute("""
                UPDATE TCC_chat_logs_uat
                SET databricks_request_id = ?
                WHERE session_id = ? AND sender = 'Assistant' AND message = ?
                AND timestamp = (
                    SELECT MAX(timestamp) FROM TCC_chat_logs_uat
                    WHERE session_id = ? AND sender = 'Assistant' AND message = ?
                )
            """, (request_id, session_id, reply, session_id, reply))
        except Exception as e:
            logging.error(f"Failed to save databricks_request_id: {e}")

    return jsonify({"status": "ok", "response": reply, "databricks_request_id": request_id})


@app.route('/api/history/<session_id>')
def get_full_history(session_id):
    try:
        cursor.execute("""
            SELECT 
                'message' AS type, 
                sender, 
                message AS message, 
                NULL AS tool_name,
                NULL AS account_number,
                timestamp AS ts
            FROM TCC_chat_logs_uat
            WHERE session_id=?
            
            UNION ALL
            
            SELECT 
                'tool' AS type,
                'Assistant' AS sender,
                result AS message,
                tool_name,
                account_number,
                run_time AS ts
            FROM TCC_tool_runs_uat
            WHERE session_id=?
            
            ORDER BY ts
        """, (session_id, session_id))
        rows = cursor.fetchall()

        history = []
        for r in rows:
            entry = {
                "type": r.type,
                "sender": r.sender,
                "message": r.message,
                "timestamp": r.ts.isoformat() if r.ts else None
            }
            if r.type == "tool":
                entry["tool_name"] = r.tool_name
                entry["account_number"] = r.account_number
            history.append(entry)

        return jsonify(history)
    except Exception as e:
        logging.error(f"Error fetching full history for session {session_id}: {e}")
        return jsonify([]), 500


@app.route('/api/run_tool', methods=['POST'])
def api_run_tool():
    data = request.get_json()
    session_id = data.get("session_id")
    save_session(session_id)

    tool_name = data.get("tool_name")
    account_number = data.get("account_number")
    company = data.get("company", None)

    results = None
    status = "failed"
    
    
    def is_16_digit_account(val):
            return (
                isinstance(val, (str, int))
                and str(val).isdigit()
                and len(str(val)) == 16
        )

    def is_non_empty_string(val):
        return isinstance(val, str) and val.strip() != ""

    # ? ServiceNow ? any non-empty string OR numeric
    if tool_name == "ServiceNow":
        if not is_non_empty_string(account_number):
            results = "ServiceNow requires a valid account number or search string"

    # ? All other tools ? exactly 16-digit numeric account
    else:
        if not is_16_digit_account(account_number):
            results = f"{tool_name} requires a valid 16-digit account number"

    # ? STOP EARLY (no external API call, no HTTP 400)
    if results:
        logging.info(results)
        save_tool_run(session_id, tool_name, account_number, company, results)

        return jsonify({
            "status": "failed",
            "tool_name": tool_name,
            "account_number": account_number,
            "results": results
        })
    
    try:

          # Execute ServiceNow API only if company is VCC and tool_name is ServiceNow
          if company == "VCC" and tool_name == "ServiceNow":
                username = get_env_setting("SERVICENOW_USERNAME", required=True)
                password = get_env_setting("SERVICENOW_PASSWORD", required=True)
                # Pass username and password
                requested_items = get_requested_item_details(account_number, username, password)
                if requested_items:
                    results = requested_items
                else:
                    results = f"No Requested Item found for account {account_number}"
                status = "ok"

          elif company == "VCC" and tool_name == "AppHub":
                results = run_apphub_tool(account_number)
                status = "ok"
          
          elif company == "TCC" and tool_name == "Modem Signal levels":
                results = run_tcc_modem_signal_tool(account_number)
                status = "ok"
            
          elif company == "TCC" and tool_name == "Equipment Details":
                results = run_tcc_equipment_details_tool(account_number)
                status = "ok"

          else:
                results = f"{tool_name} execution not applicable for company {company}"
                status = "failed"

    
    except Exception as e:
        logging.error(
            f"TCC Modem Signal tool failed | "
            f"company={company}, tool={tool_name}, account={account_number}",
            exc_info=True
        )
        results = f"API call failed: {str(e)}"
        status = "failed"


    logging.info(results)
    save_tool_run(session_id, tool_name, account_number, company, results)

    return jsonify({
        "status": status,
        "tool_name": tool_name,
        "account_number": account_number,
        "results": results
    })


@app.route('/feedback', methods=['POST'])
def api_feedback():
    data = request.get_json()
    session_id = data.get("responseId")
    feedback = data.get("feedbackScore")  # 0 or 1
    feedback_reason = data.get("reason")  # thumbs-down reason

    if not session_id or feedback not in (0, 1):
        return jsonify({"status": "error", "message": "Invalid input"}), 400

    # Default reason for thumbs-up
    if feedback == 1 or not feedback_reason:
        feedback_reason = "Satisfied"

    try:
        cursor.execute("BEGIN TRANSACTION")

        # Update last assistant message in chat logs
        cursor.execute("""
            UPDATE TCC_chat_logs_uat
            SET feedback = ?, feedback_reason = ?
            WHERE session_id = ? AND sender = 'Assistant' AND timestamp = (
                SELECT MAX(timestamp) FROM TCC_chat_logs_uat
                WHERE session_id = ? AND sender = 'Assistant'
            )
        """, (feedback, feedback_reason, session_id, session_id))

        # Update feedback in sessions table
        cursor.execute("""
            UPDATE TCC_sessions_uat
            SET feedback = ?, last_feedback_time = GETDATE()
            WHERE session_id = ?
        """, (feedback, session_id))

        # Update feedback in tool runs if applicable
        cursor.execute("""
            UPDATE TCC_tool_runs_uat
            SET feedback = ?, feedback_reason = ?
            WHERE session_id = ?
        """, (feedback, feedback_reason, session_id))

        cursor.execute("COMMIT")
        conn.commit()

        logging.info(f"Updated feedback ({feedback}) with reason '{feedback_reason}' for session {session_id}")
        return jsonify({"status": "ok", "message": "Feedback recorded"})

    except Exception as e:
        cursor.execute("ROLLBACK")
        logging.error(f"Failed to update feedback for session {session_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    #app.run(host='0.0.0.0')
    app.run(host='0.0.0.0', port=6997, threaded=True, debug=True)

