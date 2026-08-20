import time
import redis
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RunawayDetector")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

def check_runaway_velocity(agent_id: str, monthly_budget: float):
    now = time.time()
    one_hour_ago = now - 3600
    key = f"velocity:agent:{agent_id}"

    # Remove entries older than 60 minutes
    r.zremrangebyscore(key, "-inf", one_hour_ago)

    # Read rolling window spend
    entries = r.zrange(key, 0, -1, withscores=False)
    hourly_spend = 0.0
    for entry in entries:
        try:
            # Handles collision-safe entry format: timestamp:cost:uuid
            cost = float(entry.decode().split(":")[1])
            hourly_spend += cost
        except (IndexError, ValueError):
            continue

    # Trigger Condition: Velocity > 20% of monthly budget within 1 hour
    if (hourly_spend / monthly_budget) > 0.20:
        r.sadd("paused_agents", agent_id)

        alert_msg = f"CRITICAL: Agent {agent_id} PAUSED. Runaway loop detected: ${hourly_spend:.2f} spent in <1h."
        r.publish("alerts", alert_msg)
        r.lpush("alert_history", alert_msg)
        r.ltrim("alert_history", 0, 99)
        logger.error(alert_msg)
        return False

    return True

def run_worker():
    logger.info("Starting Runaway Velocity Detector background worker...")
    while True:
        try:
            for key in r.scan_iter(match="velocity:agent:*", count=100):
                agent_id = key.decode().split(":")[-1]
                budget_val = r.get(f"budget:limit:agent:{agent_id}")
                try:
                    agent_monthly_budget = float(budget_val.decode()) if budget_val else 50.00
                except (ValueError, AttributeError):
                    agent_monthly_budget = 50.00

                check_runaway_velocity(agent_id, agent_monthly_budget)
        except Exception as e:
            logger.error(f"Error scanning runaway velocity keys: {str(e)}")

        time.sleep(10)

if __name__ == "__main__":
