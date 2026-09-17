import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://recall:recall@localhost:5432/recall_monitor"
)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
