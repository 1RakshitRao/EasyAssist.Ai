"""List Groq models available on your account."""



from __future__ import annotations



import sys

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:

    sys.path.insert(0, str(ROOT))



import httpx

from dotenv import load_dotenv



load_dotenv(ROOT / ".env")



from app.config import get_settings  # noqa: E402





def main() -> None:

    settings = get_settings()

    if not settings.groq_api_key:

        raise SystemExit("Set GROQ_API_KEY in .env before running this script.")



    response = httpx.get(

        "https://api.groq.com/openai/v1/models",

        headers={"Authorization": f"Bearer {settings.groq_api_key}"},

        timeout=30.0,

    )

    response.raise_for_status()

    models = response.json()

    print("Available Groq models on your account:\n")

    for m in sorted(models["data"], key=lambda x: x["id"]):

        print(f"  {m['id']}")





if __name__ == "__main__":

    main()

