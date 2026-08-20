import streamlit as st
import redis
import json
import pandas as pd
from datetime import datetime

try:
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    r.ping()
except Exception as e:
    st.error(f"Failed to connect to Redis: {e}")
    st.stop()

st.set_page_config(page_title="Agent Budget Admin", layout="wide")
st.title("🛡️ AI Agent Budget & Routing Dashboard")

st.header("💸 Current Agent Spend")
agent_keys = r.keys("budget:agent:*")

if agent_keys:
    agent_data = []
    for key in agent_keys:
        spend_micro = int(r.get(key) or 0)
        spend_usd = spend_micro / 1_000_000
        agent_id = key.replace("budget:agent:", "")
        agent_data.append({"Agent ID": agent_id, "Spend (USD)": f"${spend_usd:.6f}", "Micro-dollars": spend_micro})
    
    st.dataframe(pd.DataFrame(agent_data), use_container_width=True)
    
    if st.button("Reset All Budgets"):
        for key in agent_keys:
            r.delete(key)
        st.success("Budgets reset! Refresh the page.")
else:
    st.info("No active agent budgets found.")

st.divider()

st.header("📜 Global Audit Trail")
session_keys = r.keys("audit:session:*")

if session_keys:
    log_data = []
    for key in session_keys:
        logs = r.lrange(key, 0, -1)
        for log in logs:
            try:
                parsed = json.loads(log)
                parsed['timestamp'] = datetime.fromtimestamp(parsed['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                log_data.append(parsed)
            except:
                pass
                
    if log_data:
        df = pd.DataFrame(log_data)
        cols = ['timestamp', 'session_id', 'agent_id', 'intent_detected', 'routed_model', 'status_code', 'actual_cost_usd', 'reason']
        cols = [c for c in cols if c in df.columns]
        df = df[cols]
        df = df.sort_values(by='timestamp', ascending=False).reset_index(drop=True)
        st.dataframe(df, use_container_width=True)
else:
    st.info("No audit logs found.")
